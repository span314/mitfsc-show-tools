#!/usr/bin/python
import csv
from collections import defaultdict, OrderedDict
import datetime
import os
import string
import subprocess

# Generate program and skate order from signup spreadsheet
# Also assumes you have ffmpeg and pdflatex installed


# Person
class Skater(object):

    def __init__(self):
        self.key = ""
        self.name = ""

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "Skater: {}".format(self.name)

    def full_name(self):
        return self.name


# Group number or individual program
class Start(object):

    def __init__(self):
        self.key = ""
        self.music_filename = ""
        self.music_url = ""
        self.length_seconds = 0
        self.blurb = ""
        self.title = ""
        self.choreographers = ""
        self.participants = list()
        self.participants_needs_sort = True

    def __repr__(self):
        return str(self)

    def __str__(self):
        return "Start: {}".format(self.key)

    def processed_music_filename(self):
        return "{}_{}.mp3".format(self.key, build_key(self.title))


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


def build_key(names):
    return "".join([c for c in names if c in string.ascii_letters])


# TODO fix unicode bugs
def strip_nonprintable(s):
    return "".join([c for c in s if c in string.printable])


def parse_starts_csv(schedule):
    print("Parsing Starts")
    starts_path = os.path.join(schedule.input_directory, "starts.csv")
    with open(starts_path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            start_key = row["Id"].strip()
            start = schedule.starts[start_key]
            start.key = start_key
            start.title = row["Title"]
            start.choreographers = row["Choreographers"]
            if row["NamesOrdered"]:
                start.participants_needs_sort = False
            skater_names = [n.strip() for n in row["Skaters"].split(",")]
            for skater_name in skater_names:
                if skater_name:
                    skater_key = build_key(skater_name)
                    skater = schedule.skaters[skater_key]
                    if not skater.name:
                        # create new skater
                        skater.key = skater_key
                        skater.name = skater_name
                    start.participants.append(skater)
            length = row["Length"]
            if length:
                time = length.split(":")
                start.length_seconds = int(time[0]) * 60 + int(time[1])
            start.blurb = row["Blurb"]
    print("Parsed Skaters")
    for skater in schedule.skaters.values():
        print(skater)
    print("Parsed Starts")
    for start in schedule.starts.values():
        print(start.key, start.title, start.participants)


def join_names(skaters, nbsp_char=None, needs_sort=True):
    if needs_sort:
        processed_skaters = sorted(skaters, key=lambda s: s.name)
    else:
        processed_skaters = skaters
    if nbsp_char:
        return ", ".join([s.name.replace(" ", nbsp_char) for s in processed_skaters])
    else:
        return ", ".join([s.name for s in processed_skaters])


def output_schedule(schedule):
    start_time = schedule.start_time + datetime.timedelta(0)
    schedule_out = os.path.join(schedule.directory, "schedule.txt")
    with open(schedule_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start_time.strftime("%I:%M:%S "))
            f.write(start.title)
            if len(start.participants) == 1:
                f.write(" - ")
                f.write(start.participants[0].name)
            f.write("\n")
            if len(start.participants) == 0:
                transition = 0
            elif 0 < len(start.participants) < 5:
                transition = max(40, 15 + len(start.blurb) // 10)
            else:
                transition = max(80, 15 + len(start.blurb) // 10)
            start_time += datetime.timedelta(seconds=start.length_seconds + transition)


def output_summary(schedule):
    summary_out = os.path.join(schedule.directory, "summary.txt")
    with open(summary_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start.key)
            f.write("  ")
            f.write(start.title)
            f.write("  ")
            f.write(str(start.length_seconds))
            f.write("\n")
            f.write(join_names(start.participants))
            f.write("\n\n")


def output_blurbs(schedule):
    blurbs_out = os.path.join(schedule.directory, "blurbs.txt")
    with open(blurbs_out, "w") as f:
        for start in schedule.sorted_starts():
            f.write(start.title)
            f.write("\n")
            participants = join_names(start.participants)
            if participants != start.title:
                f.write(participants)
                f.write("\n")
            if start.blurb and start.blurb != "TBD":
                f.write(strip_nonprintable(start.blurb))
            elif len(start.participants) > 0:
                f.write("MISSING BLURB\n\n\n\n\n\n")
            f.write("\n\n")


# deprecated in favor of html
def output_program_latex(schedule):
    halfway_cnt = len(schedule.starts) // 2
    with open("programtemplate.tex", "r") as pin, open("program.tex", "w") as pout:
        for program_row in pin:
            if program_row == "%!!!PROGRAMCONTENT\n":
                for i, start in enumerate(schedule.sorted_starts()):
                    if i == halfway_cnt:
                        pout.write("\\vfill\\null\n")
                        pout.write("\\columnbreak\n")
                    if start.title:
                        title = start.title
                        participants = join_names(start.participants, nbsp_char="~", needs_sort=start.participants_needs_sort)
                        if not participants:
                            participants = "~"
                    else:
                        title = start.participants[0].name
                        participants = "~"
                    if start.choreographers:
                        choreographers = f"\\\\Choreographed by {start.choreographers}"
                    else:
                        choreographers = ""
                    pout.write("\\programnumber{" + title + "}{" + participants + "}{" + choreographers + "}\n")
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
    subprocess.call(["/Library/TeX/texbin/pdflatex", "-halt-on-error", "-output-directory", schedule.directory, "program.tex"])


# TODO investigate html templating libraries? load from javascript?
def output_program(schedule):
    with open("templates/program/template.html", "r") as pin, open(f"{schedule.directory}/program.html", "w") as pout:
        for program_row in pin:
            program_row_no_whitespace = program_row.strip()
            if program_row_no_whitespace == "<!-- Starts -->":
                for i, start in enumerate(schedule.sorted_starts()):
                    pout.write('        <div class="start">\n')
                    if start.title:
                        title = start.title
                    else:
                        title = start.participants[0].name
                    pout.write(f'            <div class="title">{title}</div>\n')
                    if start.participants:
                        participants = join_names(start.participants,
                                                  nbsp_char="&nbsp;",
                                                  needs_sort=start.participants_needs_sort)
                        pout.write(f'            <div class="skaters">{participants}</div>\n')
                    if start.choreographers:
                        pout.write(f'            <div class="credits">{start.choreographers}</div>\n')
                    pout.write('        </div>\n')
            elif program_row_no_whitespace == "<!-- Title -->":
                if schedule.start_time.month == 12:
                    pout.write("        <div>Winter Exhibition</div>\n")
                else:
                    pout.write("        <div>Spring Exhibition</div>\n")
                formatted_date = schedule.start_time.strftime("%B %-d, %Y")
                pout.write(f"        <div>{formatted_date}</div>\n")
            else:
                pout.write(program_row)


def combine_responses(schedule):
    # locate responses file
    for filename in os.listdir(schedule.input_directory):
        if "Responses" in filename:
            break
    else:
        raise ValueError("Response file not found")
    print(f"Processing responses file: {filename}")
    responses_file_path = os.path.join(schedule.input_directory, filename)
    starts_file_path = os.path.join(schedule.input_directory, "starts.csv")
    start_rows = OrderedDict()
    fieldnames = ["Id", "Title", "Skaters", "Blurb", "Music", "Length", "Choreographers", "Comments", "NamesOrdered"]
    # read existing starts file
    if os.path.exists(starts_file_path):
        with open(starts_file_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                start_id = row["Id"].strip()
                if row["Comments"] != "SCRATCH":
                    start_rows[start_id] = row
    # read responses
    with open(responses_file_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["PreviousTitle"]:
                start_id = build_key(row["PreviousTitle"])
            else:
                start_id = build_key(row["Title"])
            row["Id"] = start_id
            if start_id in start_rows:
                if row["Comments"] == "SCRATCH":
                    # delete
                    start_rows.pop(start_id)
                else:
                    # update
                    existing_row = start_rows[start_id]
                    for field, value in row.items():
                        if value:
                            existing_row[field] = value
            else:
                if row["Comments"] != "SCRATCH":
                    # new row
                    start_rows[start_id] = row
    # output starts file
    with open(starts_file_path, "w") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, restval="", extrasaction="ignore")
        writer.writeheader()
        for start_id, start_row in start_rows.items():
            writer.writerow(start_row)


################
### WORKFLOW ###
################

if __name__ == "__main__":
    show_schedule = Schedule("winter2024", datetime.datetime(2024, 12, 8, 14, 5))
    # combine_responses(show_schedule)
    parse_starts_csv(show_schedule)
    output_summary(show_schedule)
    output_schedule(show_schedule)
    output_blurbs(show_schedule)
    output_program(show_schedule)
