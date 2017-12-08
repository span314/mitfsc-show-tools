#!/usr/bin/python
import csv
import datetime
import eyed3 #mp3 tag editor
import json
import os
import shutil
import subprocess
import urllib
import urlparse

#Generate program and skate order from signup spreadsheet
#Also assumes you have ffmpeg and pdflatex installed

#Inputs and Configuration
program_in = "programtemplate.tex"
schedule_in = "schedule_input.txt"
start_time = datetime.datetime(2017, 12, 9, 2, 5)
directory = os.path.abspath("winter2017")

#Spreadsheet In
input_spreadsheet_url = "" #google docs spreadsheet csv export link goes here
name_column = "Name"
#TODO refactor group numbers
group_columns = {
  "Group: Opening Number": "Dragon Night",
  "Group: Beginner Dance": "Dutch Waltz",
  "Group: Intermediate Dance": "Swing Dance",
  "Group: Advanced Dance": "Kilian"
}
group_times = {
  "DragonNight": 120,
  "DutchWaltz": 120,
  "SwingDance": 120,
  "Kilian": 120
}
program_columns = [
  ["Program Blurb #1", "Music Upload #1", "participants1", "program1"],
  ["Program Blurb #2", "Music Upload #2", "participants2", "program2"]
]
override_column = "Magic Override Column (not part of survey, used by my python script)"

#Class to store info on a number
class Number():
  def __init__(self, key, length_seconds, blurb, name, participants):
    self.key = key
    self.length_seconds = length_seconds
    self.blurb = blurb
    self.name = name
    participant_list = participants.split(",") if participants else []
    participant_list = [str(p).strip() for p in participant_list]
    participant_list.sort()
    self.participants = participant_list

  def __cmp__(self, other):
    return cmp(self.name, other.name)

  def __str__(self):
    print self.key
    print self.name
    print self.length_seconds
    print self.participants
    print self.blurb
    return self.key + "\n" + self.name + " " + str(self.length_seconds) + "\n" + str(self.participants) + "\n" + self.blurb

#Helpers
def get_column(row, column_name, backup_column_name=""):
  if row.get(override_column):
    overrides = json.loads(row[override_column])
    if overrides.get(column_name):
      return overrides[column_name]
  if row.get(column_name):
    return row[column_name]
  elif row.get(backup_column_name):
    return row[backup_column_name]
  else:
    return ""

def download_music(url, key):
  music_path = os.path.join(directory, key + ".mp3")
  if os.path.exists(music_path):
    print "Found cached music for " + key
  else:
    parsed_url = urlparse.urlparse(url)
    if parsed_url.netloc == "drive.google.com":
      query_params = urlparse.parse_qs(parsed_url.query)
      url = "https://drive.google.com/uc?export=download&id=" + query_params["id"][0]

    print "Downloading music for " + key + " from " + url
    (download_path, headers) = urllib.urlretrieve(url)

    original_filename = None
    for disposition in headers["Content-Disposition"].split(";"):
      disposition_parts = disposition.split("=")
      if len(disposition_parts) == 2 and disposition_parts[0] == "filename":
        original_filename = disposition_parts[1].strip("\"")

    file_extension = os.path.splitext(original_filename)[1]
    if file_extension == ".mp3":
      shutil.copy(download_path, music_path)
    elif file_extension in [".wav", ".m4a"]:
      print "Converting from " + file_extension
      subprocess.call(["ffmpeg", "-i", download_path, "-acodec", "mp3", "-ab", "192k", music_path])
    else:
      print "Error: do not know how to convert " + file_extension

    mp3_file = eyed3.load(music_path)
    if not mp3_file:
      print "Error: cannot open mp3"
      return
    if mp3_file.tag:
      mp3_file.tag.clear()
    else:
      mp3_file.initTag()
    mp3_file.tag.title = unicode(key)
    mp3_file.tag.album = u"Skating Programs"
    mp3_file.tag.save(music_path)

def read_time(key):
  music_path = os.path.join(directory, key + ".mp3")
  mp3_file = eyed3.load(music_path)
  if not mp3_file:
    print "Error: cannot open mp3"
    return 0
  return mp3_file.info.time_secs

################
### WORKFLOW ###
################

#Download Spreadsheet
input_spreadsheet_path = os.path.join(directory, "input.csv")
if os.path.exists(input_spreadsheet_path):
  print "Using cached spreadsheet"
else:
  print "Downloading live spreadsheet"
  urllib.urlretrieve(input_spreadsheet_url, input_spreadsheet_path)

#Parse data
numbers = {}
group_participants = {}
with open(input_spreadsheet_path, "r") as file_in:
  reader = csv.DictReader(file_in)
  for row in reader:
    if not row[override_column] == "SCRATCH":
      for blurb_column, music_column, participants_column, program_column in program_columns:
        name = get_column(row, program_column, name_column)
        participants = get_column(row, participants_column, name_column)
        key = filter(str.isalnum, str(participants))
        blurb = get_column(row, blurb_column)
        music = get_column(row, music_column)
        if music:
          download_music(music, key)
          seconds = read_time(key)
          numbers[key] = Number(key, seconds, blurb, name, participants)

      for group_column, group_name in group_columns.iteritems():
        group_key = filter(str.isalnum, str(group_name))
        if row[group_column]:
          if group_key in group_participants:
            group_participants[group_key] = group_participants[group_key] + ", " + get_column(row, "Name")
          else:
            group_participants[group_key] = get_column(row, "Name")
  for group_column, group_name in group_columns.iteritems():
    group_key = filter(str.isalnum, str(group_name))
    participants = group_participants.get(group_key)
    seconds = group_times.get(group_key)
    numbers[group_key] = Number(group_key, seconds, "", group_name, participants)
  #TODO Fix hack
  numbers["Intermission"] = Number("Intermission", 360, "6 Minute Warmup", "Intermission", "")

sorted_numbers = sorted(numbers.values())

#Summary of Numbers
summary_out = os.path.join(directory, "summary.txt")
with open(summary_out, "w") as f:
  for number in sorted_numbers:
    f.write(str(number))
    f.write("\n\n")

#Read Schedule
scheduled_numbers = []
with open(schedule_in, "r") as f:
  for row in f:
    scheduled_numbers.append(numbers[row.strip()])

#Schedule with Timing
schedule_out = os.path.join(directory, "schedule.txt")
with open(schedule_out, "w") as f:
  for number in scheduled_numbers:
    f.write(start_time.strftime("%I:%M:%S "))
    f.write(number.name)
    f.write("\n")
    if len(number.participants) == 0:
      transition = 0
    elif len(number.participants) < 5:
      transition = max(40, 15 + len(number.blurb) / 10)
    else:
      transition = max(90, 15 + len(number.blurb) / 10)
    start_time += datetime.timedelta(seconds = number.length_seconds + transition)

#Blurbs
blurb_out = os.path.join(directory, "blurb.txt")
with open(blurb_out, "w") as f:
  for number in scheduled_numbers:
    f.write(number.name)
    f.write("\n")
    f.write(number.blurb)
    f.write("\n\n")

#Generate Program
program_out = "program.tex"
with open(program_in, "r") as pin, open(program_out, "w") as pout:
  for program_row in pin:
    if program_row == "%!!!PROGRAMCONTENT\n":
      for number in scheduled_numbers:
        participants = ""
        if len(number.participants) > 1:
          #sort by last name
          number.participants.sort(key=lambda s: s.split()[-1])
          participants = ", ".join(number.participants)
        pout.write("\\programnumber{" + number.name + "}{" + participants + "}\n")
    else:
      pout.write(program_row)
      pout.write("\n")
subprocess.call(["pdflatex", "-halt-on-error", "-output-directory", directory, program_out])