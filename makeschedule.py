#!/usr/bin/python
from collections import defaultdict, OrderedDict
import boto3
import datetime
import eyed3  # mp3 tag editor
import json
import os
import string
import shutil
import subprocess
import tempfile

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

    def full_name(self):
        return self.first_name + " " + self.last_name


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
        self.category = None
        self.has_title = False

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "Start: {}".format(self.key)

    def processed_music_filename(self):
        return "{}_{}.mp3".format(self.key, build_key(self.name))


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
            return [s for s in self.starts.values()]
        return [self.starts[key] for key in self.start_order]


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


def build_key(names):
    return "".join([c for c in names if c in string.ascii_letters])


# TODO fix unicode bugs
def strip_nonprintable(s):
    return "".join([c for c in s if c in string.printable])


def download_music(schedule):
    if not os.path.exists(schedule.music_directory):
        os.mkdir(schedule.music_directory)
    s3 = boto3.client("s3")
    for start in schedule.starts.values():
        download_path = os.path.join(tempfile.gettempdir(), start.key)
        music_path = os.path.join(schedule.music_directory, start.processed_music_filename())
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


def parse_starts(schedule):
    print("Parsing Starts")
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

        skater_key = build_key(response["firstName"] + response["lastName"])
        skater = schedule.skaters[skater_key]
        skater.first_name = response["firstName"].strip()
        skater.last_name = response["lastName"].strip()
        skater.email = email

        for start_json in response["starts"]:
            if start_json["selected"]:
                print(start_json)
                start = schedule.starts[start_json["id"]]
                start.key = start_json["id"]
                if start_json["groupNumber"] and email != "groupnumbers@shawnpan.com":
                    start.participants.add(skater)
                else:
                    if start_json["title"]:
                        start.title = start_json["title"].strip()
                    if start_json["blurb"]:
                        start.blurb = start_json["blurb"].strip()
                    if start_json["musicFileName"]:
                        start.music_filename = start_json["musicFileName"]  # TODO

                    if start_json["skaters"]:
                        skater_names = [n.strip() for n in start_json["skaters"].split(",")]
                        for skater_name in skater_names:
                            if skater_name:
                                skater_key = build_key(skater_name)
                                participant = schedule.skaters[skater_key]
                                # create new skater if necessary
                                if not participant.first_name:
                                    skater_name_parts = [n.replace("_", " ") for n in skater_name.strip().split(" ")]
                                    if len(skater_name_parts) == 2:
                                        participant.first_name, participant.last_name = skater_name_parts
                                    elif len(skater_name_parts) == 1:
                                        participant.first_name = skater_name_parts[0]
                                    else:
                                        print "Use underscores to group names: " + skater_name  # TODO handle parsing better
                                start.participants.add(participant)
                    elif email != "groupnumbers@shawnpan.com":
                        start.participants.add(skater)

                    if start.title:
                        start.name = start.title
                        start.has_title = start.title != skater.full_name()
                    else:
                        # TODO fix
                        start.has_title = False
                        raise ValueError("start without title")
                    # strip_nonprintable?
    print ("Parsed Skaters")
    for skater in schedule.skaters.itervalues():
        print (skater)
    print ("Parsed Starts")
    for start in schedule.starts.itervalues():
        print (start.key, start.title, start.participants)


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
                        participants.append(join_names(start.participants, name_sep="~", should_sort=(len(start.participants) > 2)) + " ")
                    pout.write("\\programnumber{" + start.name + "}{" + "\\\\".join(participants) + "}\n")
                    if start.category == "intermission":
                        pout.write("\\vfill\\null\n")
                        pout.write("\\columnbreak\n")
            elif program_row == "%!!!SHOWDATE\n":
                pout.write(schedule.start_time.strftime("%B %-d, %Y"))
            elif program_row == "%!!!SHOWTITLE\n":
                if schedule.start_time.month == 12:
                    pout.write("Winter Exhibition")
                else:
                    pout.write("Spring Exhibition")
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
        music_path = os.path.join(schedule.music_directory, start.processed_music_filename())
        if os.path.exists(music_path):
            track += 1
            new_filename = "{:02d}_{}_{}.mp3".format(track, start.key, build_key(start.title))
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
download_music(show_schedule)
output_keys(show_schedule)
parse_skate_order(show_schedule)
output_summary(show_schedule)
output_schedule(show_schedule)
output_blurbs(show_schedule)
output_program(show_schedule)
prepare_music_for_disk(show_schedule)

