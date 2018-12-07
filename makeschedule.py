#!/usr/bin/python
from collections import defaultdict
import csv
import datetime
import eyed3  # mp3 tag editor
import os
import re
import string
import shutil
import subprocess
import urllib
import urlparse

# Generate program and skate order from signup spreadsheet
# Also assumes you have ffmpeg and pdflatex installed


# Person
class Skater(object):

    def __init__(self):
        self.key = ""
        self.first_name = ""
        self.last_name = ""
        self.email = ""

    def full_name(self):
        return "{} {}".format(self.first_name, self.last_name)

    def __cmp__(self, other):
        last_name_cmp = cmp(self.last_name, other.last_name)
        if last_name_cmp:
            return last_name_cmp
        return cmp(self.first_name, other.first_name)

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "Skater: {} {}".format(self.first_name, self.last_name)


# Group number or individual program
class Start(object):

    def __init__(self):
        self.key = ""
        self.music_filename = ""
        self.music_url = ""
        self.length_seconds = 0
        self.blurb = ""
        self.name = ""
        self.participants = set()
        self.scratch = False

    def sorted_participants(self):
        return ", ".join([p.full_name() for p in sorted(self.participants)])

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "Start: {}".format(self.key)


# Schedule state
class Schedule(object):

    def __init__(self, directory, start_time):
        self.directory = os.path.abspath(directory)
        self.input_directory = os.path.join(directory, "inputs")
        self.music_directory = os.path.join(directory, "music")
        self.starts = defaultdict(Start)
        self.skaters = defaultdict(Skater)
        self.start_order = []
        self.start_time = start_time

    def sorted_starts(self):
        if not self.start_order:
            return [s for s in self.starts.values() if not s.scratch]
        return [self.starts[key] for key in self.start_order]


# Download csv file if necessary (using google sheets key in filename.csv.key)
def download_csv(directory, filename, cache=True):
    path = os.path.join(directory, filename)
    if cache and os.path.exists(path):
        print "Using cached spreadsheet {}".format(filename)
        return path
    key_path = path + ".key"
    if os.path.exists(key_path):
        print "Downloading spreadsheet {}".format(filename)
        with open(key_path, "r") as key_file:
            spreadsheet_key = key_file.read().strip()
        url = "https://docs.google.com/spreadsheets/d/" + spreadsheet_key + "/export?format=csv"
        urllib.urlretrieve(url, path)
        return path
    else:
        raise ValueError("Failed to find file {}".format(filename))


# TODO multiple numbers by same person
def build_key(names):
    key = names
    return "".join([c for c in key if c in string.ascii_letters])


# TODO fix unicode bugs
def strip_nonprintable(s):
    return "".join([c for c in s if c in string.printable])


def download_music(schedule):
    if not os.path.exists(schedule.music_directory):
        os.mkdir(schedule.music_directory)
    for start in schedule.starts.values():
        music_path = os.path.join(schedule.music_directory, start.music_filename + ".mp3")

        if os.path.exists(music_path):
            print "Found cached music for " + start.key
        else:
            if not start.music_url:
                continue  #TODO fix
            parsed_url = urlparse.urlparse(start.music_url)
            if parsed_url.netloc == "drive.google.com":
                query_params = urlparse.parse_qs(parsed_url.query)
                url = "https://drive.google.com/uc?export=download&id=" + query_params["id"][0]

            print "Downloading music for " + start.key + " from " + url + " to " + music_path
            (download_path, headers) = urllib.urlretrieve(url)

            original_filename = None

            for disposition in headers["Content-Disposition"].split(";"):
                disposition_parts = disposition.split("=")
                if len(disposition_parts) == 2 and disposition_parts[0] == "filename":
                    original_filename = disposition_parts[1].strip("\"")

            file_extension = os.path.splitext(original_filename)[1]
            if file_extension.lower() == ".mp3":
                shutil.copy(download_path, music_path)
            elif file_extension.lower() == ".cda":
                print "Error: Received link rather than music"
                return False
            else:
                if file_extension.lower() not in [".wav", ".m4a", ".aif", ".aiff", ".wma", ".mp2"]:
                    print "Warning unusual filetype " + file_extension
                print "Converting from " + file_extension
                subprocess.call(["ffmpeg", "-y", "-i", download_path, "-acodec", "mp3", "-ab", "256k", music_path])

            mp3_file = eyed3.load(music_path)
            if not mp3_file:
                print "Error: cannot open mp3"
                return
            if mp3_file.tag:
                mp3_file.tag.clear()
            else:
                mp3_file.initTag()
            mp3_file.tag.title = unicode(start.name)
            mp3_file.tag.album = u"Skating Programs"
            mp3_file.tag.save(music_path)

        # read time
        mp3_file = eyed3.load(music_path)
        if not mp3_file:
            print "Error: cannot open mp3"
            return 0
        start.length_seconds = mp3_file.info.time_secs


def parse_group_numbers(schedule):
    input_survey_path = download_csv(schedule.input_directory, "group.csv")
    with open(input_survey_path, "r") as file_in:
        reader = csv.DictReader(file_in)
        group_numbers = {}
        for column in reader.fieldnames:
            group_number_match = re.search("Group Numbers \\[(.*?)\\]", column)
            if group_number_match:
                start = schedule.starts[build_key(column)]
                start.name = group_number_match.group(1)
                group_numbers[column] = start
        for row in reader:
            first_name = row["First Name"].strip()
            last_name = row["Last Name"].strip()
            email = row["Email Address"].strip()
            skater_key = build_key(first_name + last_name)
            skater = schedule.skaters[skater_key]
            skater.first_name = first_name
            skater.last_name = last_name
            skater.email = email
            for column, group_number in group_numbers.iteritems():
                if row[column]:
                    group_number.participants.add(skater)
                else:
                    group_number.participants.discard(skater)


def parse_starts(schedule):
    input_survey_path = download_csv(schedule.input_directory, "starts.csv")
    with open(input_survey_path, "r") as file_in:
        reader = csv.DictReader(file_in)
        for i, row in enumerate(reader):
            names = row["Name(s)"]
            title = strip_nonprintable(row["Program Title (optional)"])
            title = title if title else names
            music = row["Music Upload"]
            if music.isdigit():
                length = int(music)
                music_url = ""
            else:
                length = 0
                music_url = music
            blurb = strip_nonprintable(row["Introduction Blurb for Announcer"])
            if title and title.startswith("Group Number"):
                key = build_key(title)
            else:
                key = build_key(names)
            music_filename = key + str(i)

            start = schedule.starts[key]
            start.key = key
            start.music_filename = music_filename

            if title:
                start.name = title
            if music_url:
                start.music_url = music_url
            if length:
                start.length_seconds = length
            if blurb:
                start.blurb = blurb
            start.order = i

            if title.startswith("SCRATCH"):  #TODO fix hack
                start.scratch = True

            for skater_name in names.split(","):
                if skater_name:
                    skater_key = build_key(skater_name)
                    skater = schedule.skaters[skater_key]
                    if not skater.first_name:
                        skater_name_parts = skater_name.strip().split(" ")
                        if len(skater_name_parts) == 2:
                            skater.first_name, skater.last_name = skater_name_parts
                        elif len(skater_name_parts) == 1:
                            skater.first_name = skater_name_parts[0]
                        else:
                            print "ERROR TODO handle name parsing better: " + skater_name
                    start.participants.add(skater)


def parse_skate_order(schedule):
    skate_order_path = os.path.join(schedule.input_directory, "skate_order.txt")
    with open(skate_order_path, "r") as file_in:
        schedule.start_order = []
        for row in file_in:
            schedule.start_order.append(row.strip())


def output_schedule(schedule):
    start_time = schedule.start_time + datetime.timedelta(0)
    schedule_out = os.path.join(schedule.directory, "schedule.txt")
    with open(schedule_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start_time.strftime("%I:%M:%S "))
            f.write(start.name)
            f.write("\n")
            f.write("         ")
            f.write(start.sorted_participants())
            f.write("\n")
            if len(start.participants) == 0:
                transition = 0
            elif len(start.participants) < 5:
                transition = max(40, 15 + len(start.blurb) / 10)
            else:
                transition = max(90, 15 + len(start.blurb) / 10)
            start_time += datetime.timedelta(seconds=start.length_seconds + transition)


def output_keys(schedule):
    keys_out = os.path.join(schedule.directory, "keys.txt")
    with open(keys_out, "w") as f:
        for start in schedule.sorted_starts():
            print start
            f.write(start.key)
            f.write("\n")


def output_summary(schedule):
    summary_out = os.path.join(schedule.directory, "summary.txt")
    with open(summary_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start.key)
            f.write("  ")
            f.write(start.name)
            f.write("  ")
            f.write(str(start.length_seconds))
            f.write("\n")
            f.write(start.sorted_participants())
            f.write("\n\n")


def output_blurbs(schedule):
    blurbs_out = os.path.join(schedule.directory, "blurbs.txt")
    with open(blurbs_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start.name)
            f.write("\n")
            participants = start.sorted_participants()
            if participants != start.name:
                f.write(participants)
                f.write("\n")
            if start.blurb:
                f.write(start.blurb)
            else:
                f.write("MISSING BLURB\n\n\n\n\n\n")
            f.write("\n\n")


def output_program(schedule):
    with open("programtemplate.tex", "r") as pin, open("program.tex", "w") as pout:
        for program_row in pin:
            if program_row == "%!!!PROGRAMCONTENT\n":
                for start in schedule.sorted_starts():
                    participants = start.sorted_participants()
                    if participants == start.name:
                        participants = ""
                    pout.write("\\programnumber{" + start.name + "}{" + participants + "}\n")
            else:
                pout.write(program_row)
                pout.write("\n")
    subprocess.call(["pdflatex", "-halt-on-error", "-output-directory", schedule.directory, "program.tex"])


def prepare_music_for_disk(schedule):
    ordered_music_directory = schedule.music_directory + "_ordered"
    if not os.path.exists(ordered_music_directory):
        os.mkdir(ordered_music_directory)
    track = 0
    for start in schedule.sorted_starts():
        music_path = os.path.join(schedule.music_directory, start.music_filename + ".mp3")
        if os.path.exists(music_path):
            track += 1
            new_filename = "{:02d}_{}.mp3".format(track, start.key)
            new_music_path = os.path.join(ordered_music_directory, new_filename)
            shutil.copy(music_path, new_music_path)
            mp3_file = eyed3.load(new_music_path)
            mp3_file.tag.track = track
            mp3_file.tag.save(new_music_path)


################
### WORKFLOW ###
################

winter2018show = Schedule("winter2018", datetime.datetime(2018, 12, 9, 1, 05))
parse_starts(winter2018show)
parse_group_numbers(winter2018show)
parse_skate_order(winter2018show)
download_music(winter2018show)
output_keys(winter2018show)
output_summary(winter2018show)
output_schedule(winter2018show)
output_blurbs(winter2018show)
output_program(winter2018show)
prepare_music_for_disk(winter2018show)

