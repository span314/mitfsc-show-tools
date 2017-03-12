#!/usr/bin/python
import contextlib
import csv
import datetime
import os
import subprocess
import urllib2

#Inputs
program_in = "programtemplate.tex"
#responses can be either a local file or google docs url
responses_in = "https://docs.google.com/spreadsheets/d/1YfcUZwbrqp92gmuJFa6I7HCGQyE6iygURLmlrOC5J_Q/export?format=csv"
schedule_in = "schedule_input.txt"
start_time = datetime.datetime(2017, 3, 12, 6, 35)

#Outputs
email_out = "emails.txt"
program_out = "program.tex"
schedule_out = "schedule.txt"
summary_out = "summary.txt"
blurb_out = "blurb.txt"

#Class to store info on a number
class Number():
  def __init__(self, key, length, blurb, name):
    self.key = key
    self.length = length
    h, m, s = length.split(":")
    self.length_seconds = 3600 * int(h) + 60 * int(m) + int(s)
    self.blurb = blurb
    self.name = name
    self.participants = []

  def __cmp__(self, other):
    return cmp(self.name, other.name)

  def __str__(self):
    return self.name + " " + self.length + "\n" + str(sorted(self.participants)) + "\n" + self.blurb

#Parse data
numbers = {}
responses_in = "file://" + urllib2.quote(os.path.abspath(responses_in)) if "://" not in responses_in else responses_in

with contextlib.closing(urllib2.urlopen(responses_in)) as f:
  reader = csv.DictReader(f)
  for row in reader:
    #add solo numbers
    if row["Program Length"]:
      number = Number(row["Key"], row["Program Length"], row["Blurb"], row["Name"])
      if row["Comments or Requests"] != "GROUP": #TODO fix this hack
        number.participants.append(row["Name"])
      numbers[number.key] = number
    #add group numbers
    for key, number in numbers.iteritems():
      if key in row["Group Numbers"]:
        number.participants.append(row["Name"])

sorted_numbers = sorted(numbers.values())

#Summary of Numbers
with open(summary_out, "w") as f:
  for number in sorted_numbers:
    f.write(str(number))
    f.write("\n\n")

#Read Schedule
scheduled_numbers = []
with open(schedule_in, "r") as sin:
  for row in sin:
    scheduled_numbers.append(numbers[row.strip()])

#Schedule with Timing
with open(schedule_out, "w") as sout:
  for number in scheduled_numbers:
    sout.write(start_time.strftime("%I:%M:%S "))
    sout.write(number.name)
    sout.write("\n")
    if len(number.participants) == 0:
      transition = 0
    elif len(number.participants) < 5:
      transition = max(40, 15 + len(number.blurb) / 10)
    else:
      transition = max(90, 15 + len(number.blurb) / 10)
    start_time += datetime.timedelta(seconds = number.length_seconds + transition)

#Blurbs
with open(blurb_out, "w") as bout:
  for number in scheduled_numbers:
    bout.write(number.name)
    bout.write("\n")
    bout.write(number.blurb)
    bout.write("\n\n")

#Generate Program
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
print os.path.abspath(program_out)
subprocess.call(["pdflatex", program_out])