#!/usr/bin/python
from collections import defaultdict, OrderedDict
import boto3
import csv
import datetime
import eyed3  # mp3 tag editor
import json
import os
import re
import string
import shutil
import subprocess
import urllib
import urlparse
from botocore.exceptions import ClientError

# Generate program and skate order from signup spreadsheet
# Also assumes you have ffmpeg and pdflatex installed


# Person
class Skater(object):

    def __init__(self):
        self.key = ""
        self.first_name = ""
        self.last_name = ""
        self.email = ""
        self.order = 0

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
        self.participant_subgroup = OrderedDict()
        self.scratch = False
        self.category = None
        self.has_title = False

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


def dump_dynamo_table(directory, table_name, cache=True):
    path = os.path.join(directory, table_name + ".txt")
    if cache and os.path.exists(path):
        print "Using cached data for table {}".format(table_name)
    else:
        print "Scanning table {}".format(table_name)
        dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
        table = dynamodb.Table(table_name)
        with open(path, "w") as table_file:
            scan_responses = table.scan()
            for item in scan_responses["Items"]:
                table_file.write(item["email"])
                table_file.write("\n")
                table_file.write(item["response"])
                table_file.write("\n")
            while "LastEvaluatedKey" in scan_responses:
                scan_responses = table.scan(ExclusiveStartKey=scan_responses["LastEvaluatedKey"])
                for item in scan_responses["Items"]:
                    table_file.write(item["email"])
                    table_file.write("\n")
                    table_file.write(item["response"])
                    table_file.write("\n")
    return path


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
    s3 = boto3.client("s3")
    for start in schedule.starts.values():
        download_path = os.path.join(schedule.music_directory, start.key + "__" + start.music_filename)
        music_path = os.path.join(schedule.music_directory, start.key + ".mp3")
        if os.path.exists(music_path):
            print "Found cached music for " + start.key
        elif not start.music_filename:
            print "No music submitted for " + start.key
            continue # TODO
        else:
            print "Downloading music for " + start.key + " to " + download_path
            s3.download_file("music.shawnpan.com", start.key, download_path)

            file_extension = os.path.splitext(start.music_filename)[1]
            if file_extension.lower() == ".mp3":
                shutil.copy(download_path, music_path)
            elif file_extension.lower() == ".cda":
                print "Error: Received link rather than music"
                return False  # TODO
            else:
                if file_extension.lower() not in [".wav", ".m4a", ".aif", ".aiff", ".wma", ".mp2"]:
                    print "Warning unusual filetype " + file_extension
                print "Converting from " + file_extension
                subprocess.call(["ffmpeg", "-y", "-i", download_path, "-acodec", "mp3", "-ab", "256k", music_path])

            mp3_file = eyed3.load(music_path)
            if not mp3_file:
                print "Error: cannot open mp3"
                return  # TODO
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
            return 0  # TODO
        print mp3_file.info.time_secs
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
    input_survey_path = dump_dynamo_table(schedule.input_directory, "skating-survey-responses")
    responses = {}
    with open(input_survey_path, "r") as file_in:
        while True:
            line1 = file_in.readline()
            line2 = file_in.readline()
            if not line1 or not line2:
                break  # EOF
            responses[line1.strip()] = json.loads(line2)

    for email, response in responses.iteritems():
        print(email)

        skater_key = build_key(response["firstName"] + response["lastName"])  # TODO email as key
        skater = schedule.skaters[skater_key]
        skater.first_name = response["firstName"].strip()
        skater.last_name = response["lastName"].strip()
        skater.email = email

        for start_json in response["starts"]:
            if start_json["selected"]:
                print(start_json)
                start = schedule.starts[start_json["id"]]
                start.key = start_json["id"]
                if start_json["title"]:
                    start.title = start_json["title"].strip()
                if start_json["blurb"]:
                    start.blurb = start_json["blurb"].strip()
                if start_json["musicFileName"]:
                    start.music_filename = start_json["musicFileName"]  # TODO

                if start_json["skaters"]:
                    subgroups = split_subgroups(start_json["skaters"])
                    for subgroup_header, subgroup_names in subgroups.iteritems():
                        subgroup_skaters = []
                        for skater_name in subgroup_names:
                            if skater_name:
                                skater_key = build_key(skater_name)
                                skater2 = schedule.skaters[skater_key]
                                if not skater2.first_name:
                                    skater_name_parts = [n.replace("_", " ") for n in skater_name.strip().split(" ")]
                                    if len(skater_name_parts) == 2:
                                        skater2.first_name, skater2.last_name = skater_name_parts
                                    elif len(skater_name_parts) == 1:
                                        skater2.first_name = skater_name_parts[0]
                                    else:
                                        print "ERROR TODO handle name parsing better: " + skater_name
                                subgroup_skaters.append(skater2)
                        start.participants.update(subgroup_skaters)
                        start.participant_subgroup[subgroup_header] = subgroup_skaters
                elif email != "groupnumbers@shawnpan.com":
                    start.participants.add(skater)

                if start.title:
                    start.name = start.title
                    start.has_title = True
                else:
                    # TODO fix
                    start.has_title = False
                    raise ValueError("start without title")
                # start.order = i++
                # strip_nonprintable?
                # start_json["groupNumber"]

    print(schedule.skaters)
    for start in schedule.starts.itervalues():
        print (start.key, start.title, start.participants)


        #
        #
        #
        # reader = csv.DictReader(file_in)
        # for i, row in enumerate(reader):
        #     names = row["Skater Name(s)"]
        #     category = row["Category"]
        #     title = strip_nonprintable(row["Program Title (optional)"])
        #     music = row["Music Upload"]
        #     if music.isdigit():
        #         length = int(music)
        #         music_url = ""
        #     else:
        #         length = 0
        #         music_url = music
        #     blurb = strip_nonprintable(row["Introduction Blurb for Announcer"])
        #     if category == "group" or category == "intermission":
        #         key = build_key(title)
        #     else:
        #         key = build_key(names)
        #     music_filename = key + str(i)
        #
        #     start = schedule.starts[key]
        #     start.key = key
        #     start.category = category
        #     start.music_filename = music_filename
        #
        #     if title:
        #         start.name = title
        #         start.has_title = True
        #     else:
        #         start.name = names
        #         start.has_title = False
        #     if music_url:
        #         start.music_url = music_url
        #     if length:
        #         start.length_seconds = length
        #     if blurb:
        #         start.blurb = blurb
        #     start.order = i
        #
        #     if category == "scratch":
        #         start.scratch = True
        #
        #     subgroups = split_subgroups(names)
        #     for subgroup_header, subgroup_names in subgroups.iteritems():
        #         subgroup_skaters = []
        #         for skater_name in subgroup_names:
        #             if skater_name:
        #                 skater_key = build_key(skater_name)
        #                 skater = schedule.skaters[skater_key]
        #                 if not skater.first_name:
        #                     skater_name_parts = [n.replace("_", " ") for n in skater_name.strip().split(" ")]
        #                     if len(skater_name_parts) == 2:
        #                         skater.first_name, skater.last_name = skater_name_parts
        #                     elif len(skater_name_parts) == 1:
        #                         skater.first_name = skater_name_parts[0]
        #                     else:
        #                         print "ERROR TODO handle name parsing better: " + skater_name
        #                 subgroup_skaters.append(skater)
        #         start.participants.update(subgroup_skaters)
        #         start.participant_subgroup[subgroup_header] = subgroup_skaters


def split_subgroups(names):
    subgroups = OrderedDict()

    subgroup_parts = names.split(":")
    if len(subgroup_parts) % 2 == 1:
        subgroup_parts = ["default"] + subgroup_parts

    for i in range(0, len(subgroup_parts), 2):
        subgroup_header = subgroup_parts[i].strip()
        subgroup_names = subgroup_parts[i + 1].strip()
        subgroups[subgroup_header] = [n.strip() for n in subgroup_names.split(",")]

    return subgroups


def join_names(skaters, skater_sep=", ", name_sep=" ", should_sort=True):
    if should_sort:
        processed_skaters = sorted(skaters)
    else:
        processed_skaters = skaters
    return skater_sep.join([name_sep.join([p.first_name, p.last_name]) for p in processed_skaters])


def parse_skate_order(schedule):
    skate_order_path = os.path.join(schedule.input_directory, "skate_order.txt")
    with open(skate_order_path, "r") as file_in:
        schedule.start_order = []
        for row in file_in:
            parts = row.split()
            if parts:
                schedule.start_order.append(parts[0])


def output_schedule(schedule):
    start_time = schedule.start_time + datetime.timedelta(0)
    schedule_out = os.path.join(schedule.directory, "schedule.txt")
    with open(schedule_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start_time.strftime("%I:%M:%S "))
            f.write(start.name)
            f.write("\n")
            f.write("         ")
            f.write(join_names(start.participants))
            f.write("\n")
            if start.category == "intermission":
                transition = 0
            elif 0 < len(start.participants) < 5:
                transition = max(40, 15 + len(start.blurb) / 10)
            else:
                transition = max(80, 15 + len(start.blurb) / 10)
            start_time += datetime.timedelta(seconds=start.length_seconds + transition)


def output_keys(schedule):
    keys_out = os.path.join(schedule.directory, "keys.txt")
    with open(keys_out, "w") as f:
        for start in schedule.sorted_starts():
            print start
            f.write(start.key)
            f.write(" ")
            f.write(start.title)
            f.write(" ")
            f.write(" ".join([skater.first_name for skater in start.participants]))
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
            f.write(join_names(start.participants))
            f.write("\n\n")


def output_blurbs(schedule):
    blurbs_out = os.path.join(schedule.directory, "blurbs.txt")
    with open(blurbs_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start.name)
            f.write("\n")
            participants = join_names(start.participants)
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
                    print(start.name)
                    participants = []
                    if start.has_title:
                        for subgroup_header, subgroup_participants in start.participant_subgroup.iteritems():
                            if subgroup_header != "default":
                                participants.append("\\vspace{0.05in} \\textbf{" + subgroup_header + "} ")
                            participants.append(join_names(subgroup_participants, name_sep="~", should_sort=(len(subgroup_participants) > 2)) + " ")
                    pout.write("\\programnumber{" + start.name + "}{" + "\\\\".join(participants) + "}\n")
                    if start.category == "intermission":
                        pout.write("\\vfill\\null\n")
                        pout.write("\\columnbreak\n")
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

show_schedule = Schedule("winter2019", datetime.datetime(2019, 12, 8, 17, 05))
parse_starts(show_schedule)
# parse_group_numbers(spring2019show) XXX
parse_skate_order(show_schedule)
download_music(show_schedule)
output_keys(show_schedule)
output_summary(show_schedule)
output_schedule(show_schedule)
output_blurbs(show_schedule)
output_program(show_schedule)
# prepare_music_for_disk(spring2019show)

