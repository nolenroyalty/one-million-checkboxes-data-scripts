#!/usr/bin/env python
import argparse
import shutil
import subprocess
import datetime
import os
import sys
import bitarray
import tempfile
from PIL import Image, ImageDraw
import numpy as np
from math import log as log_func

dt = datetime.datetime

class DefaultValue(int):
    # quick way to check whether the user is passing a default argument on the command line
    pass

def isodate(s):
    # older datetime versions don't do this??
    return dt.fromisoformat(s.replace("Z", "+00:00"))

def quickdate(month, day, hour=0, minute=0, second=0):
    return isodate(f"2024-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}Z")

# OMCB had three "eras"
# 1. When I brought the site up to when it crashed during night one
# 2. When I brought the site back up after the crash
# 3. When I brought the site down and reset its state to sunset the site
# 
# The state changes between these eras, and there's also substantial downtime between them.
# We track them separately so that we know when to load a new state snapshot and to account
# for downtime (to avoid producing timelapses with a bunch of still frames)
#
# note that I dropped several hours of data after launching the site because I wasn't keeping
# enough logs. Oops.
eras_by_date_range = [
        (isodate("2024-06-26T19:00:40Z"), isodate("2024-06-27T08:40:35Z"), "pre-crash"),
        (isodate("2024-06-27T13:12:37Z"), isodate("2024-07-11T16:32:29Z"), "post-crash-pre-sunset"),
        (isodate("2024-07-11T16:37:47Z"), isodate("2024-07-11T20:35:05Z"), "post-sunset")]

def start_of_era(era):
    return [start for (start, _, era_) in eras_by_date_range if era == era_][0]

def end_of_era(era):
    return [end for (_, end, era_) in eras_by_date_range if era == era_][0]

START = start_of_era("pre-crash")
END = end_of_era("post-sunset")

def within_range_where_site_was_up(date):
    return date >= START and date < END

def within_range_where_site_was_up_exn(date):
    v = within_range_where_site_was_up(date)
    if not v:
        raise Exception(f"{date} is outside of range where we have data - data is available from {START} to {END}")

def validate_start_and_end_dates(start, end):
    if start > end:
        raise Exception(f"Start date is after end date! {start} > {end}")

    within_range_where_site_was_up_exn(start)
    within_range_where_site_was_up_exn(end)

def get_era_for_date(date):
    within_range_where_site_was_up_exn(date)
    for (start, end, era) in eras_by_date_range:
        if start <= date <= end:
            return era
    raise Exception(f"Date satisfied no eras? Should be impossible {date}")

def prepend_data_path(name, era, provided_data_path=None):
    basedir = provided_data_path
    if basedir is None:
        basedir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        basedir = os.path.join(basedir, "omcb-data")
    
    era_dir = os.path.join(basedir, era)
    return os.path.join(era_dir, name)

def get_snapshot_name_for_date(date, era=None, data_path=None):
    era = era if era is not None else get_era_for_date(date)
    start = start_of_era(era)
    name = None
    if start.day == date.day:
        name = "initial.db"
    else:
        d = date - datetime.timedelta(days=1)
        name = f"snapshot.{d.year}-{d.month:02}-{d.day:02}.db"

    return prepend_data_path(name, era, provided_data_path=data_path)

def get_log_name_for_date(date, era=None, data_path=None):
    era = era if era is not None else get_era_for_date(date)
    name = f"logs.{date.year}-{date.month:02}-{date.day:02}.txt"
    return prepend_data_path(name, era, provided_data_path=data_path)

def apply_line_to_state(state, line, after=None, before=None):
    line = line.strip()
    date, cell, value = line.split("|")

    date += "Z"
    date = isodate(date)
    cell = int(cell)

    if after is not None and date < after: return (state, date, "before-first")
    if before is not None and date > before: return (state, date, "past-last")

    if value == "1":
        state[cell] = 1
    elif value == "0":
        state[cell] = 0
    else:
        raise Exception(f"wtf? {line} {value}")

    return (state, date, "continue")

def apply_line_to_state_heatmap(state, line, after=None, before=None):
    line = line.strip()
    date, cell, value = line.split("|")

    date += "Z"
    date = isodate(date)
    cell = int(cell)

    if after is not None and date < after: return (state, date, "before-first")
    if before is not None and date > before: return (state, date, "past-last")
    
    if value == "1":
        state[int(cell)] = 1
    elif value == "0":
        state[int(cell)] = 0

    return (state, date, "continue")

def apply_logs_to_state(state, log_name, cutoff_date):
    with open(log_name, "r") as f:
        for i, line in enumerate(f):
            if i % 150000 == 0:
                print(f"processed {i} lines")
            state, _date, status = apply_line_to_state(state, line, before=cutoff_date)
            if status == "past-last":
                break

    return state

def state_of_snapshot(snapshot):
    state = bitarray.bitarray()
    with open(snapshot, "rb") as f:
        state.frombytes(f.read(125000))
    return state

def blank_int_snapshot():
    state = [0] * 1000000
    return state

def add_to_snapshot(new, old, diff):
    #uncomment to replace state with snapshot (also change state in args)
    #with open(snapshot, "rb") as f:
    #    state = [int(d) for d in str(bin(int.from_bytes(f.read(125000), byteorder="big")).lstrip('0b'))]
    #    if len(state) < 1000000:
    #        state = ([0] * (1000000 - len(state))) + state
    for idx, bit in enumerate(new):
        if old[idx] != new[idx]: diff[idx] += 1
    return diff

def state_at_time_command(args):
    date = args.datetime
    outfile = args.output
    data_path = args.data_directory

    within_range_where_site_was_up_exn(date)
    era = get_era_for_date(date)
    snapshot = get_snapshot_name_for_date(date, data_path=data_path)
    log_name = get_log_name_for_date(date, data_path=data_path)

    state = state_of_snapshot(snapshot)
    apply_logs_to_state(state, log_name, date)

    with open(outfile, "wb") as f:
        f.write(state.tobytes())

def check_ffmpeg():
    """
    Check if ffmpeg is available in the system PATH.
    Raises a RuntimeError if ffmpeg is not found.
    """
    if shutil.which('ffmpeg') is None:
        raise RuntimeError("FFmpeg not found. Please install FFmpeg and make sure it's in your PATH.")

    try:
        subprocess.run(['ffmpeg', '-version'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except subprocess.CalledProcessError:
        raise RuntimeError("FFmpeg is installed but not working correctly.")

def image_of_state(state, outfile):
    subprocess.run(
            ["ffmpeg", 
             "-f", "rawvideo", 
             "-pix_fmt", "monob", 
             "-video_size", "1000x1000", 
             "-i", 
             "-",
             "-y", outfile], 
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            input=state.tobytes())

def image_of_heatmap(state, outfile, logarithmic):
    arr = np.array(state)
    max_val = int(np.max(arr))
    img = Image.new('RGB', (1000, 1000))
    draw = ImageDraw.Draw(img)
    for i in range(1000):
        print("Converting to image: " + str(round((i/1000)*100, 0)) + "%", end="\r")
        for j in range(1000):
            color = (arr[(i*1000) + j] / max_val)
            init = int(color * 255)
            for x in range(logarithmic):
                color = log_func((color*0.9 + 0.1), 10) + 1
            if color > 1:
                print(init, color)
            color = int(color * 255)
            draw.point((j, i), fill=(color, color, color))
    print()
    img.save(outfile)

def video_of_images(directory, outfile, framerate=30):
    img_path = os.path.join(directory, "img-*.png")
    res = subprocess.run(
            ["ffmpeg",
            "-framerate", str(framerate),
            "-pattern_type", "glob",
            "-i", img_path,
            "-pix_fmt", "gray",
            "-video_size", "1000x1000",
            "-c:v", "libx264",
            "-y", outfile],
            capture_output=True,
            text=True)

def date_range(start, end):
    cur = start
    dates = []
    while cur <= end:
        dates.append(cur)
        # gross, but let's just hardcode this
        crash_end = eras_by_date_range[0][1]
        post_crash_start = eras_by_date_range[1][0]
        post_crash_end = eras_by_date_range[1][1]
        post_sunset_start = eras_by_date_range[2][0]

        if cur.day == crash_end.day and cur.month == crash_end.month:
            if cur < crash_end and end > crash_end:
                dates.append(post_crash_start)
        if cur.day == post_crash_end.day and cur.month == post_crash_end.month:
            if cur < post_crash_end and end > post_crash_end:
                dates.append(post_sunset_start)

        try:
            cur = cur.replace(day=cur.day+1, hour=0, minute=0, second=0)
        except:
            cur = cur.replace(day=1, month=cur.month+1, hour=0, minute=0, second=0)

    return dates

class TimelapseStrategy:
    def __init__(self, snapshot_every_n_checks, snapshot_every_i_seconds):
        self.count = None
        self.last_snapshot_time = None
        self.snapshot_every_n_checks = snapshot_every_n_checks
        self.snapshot_every_i_seconds = datetime.timedelta(seconds=snapshot_every_i_seconds)

        if snapshot_every_n_checks is None and snapshot_every_i_seconds is None:
            raise Exception("Neither snapshot frequency passed. This shouldn't be possible?")
        if snapshot_every_n_checks is None:
            self.strategy = "seconds"
        elif snapshot_every_n_checks is not None and isinstance(snapshot_every_i_seconds, DefaultValue):
            self.strategy = "checks"
        elif snapshot_every_n_checks is not None and not isinstance(snapshot_every_i_seconds, DefaultValue):
            self.strategy = "both"

    def reset_date_for_new_era(self):
        # because there's a reasonably large gap between each "era" we don't really
        # want to have a timelapse that's perfectly still for a bunch of hours (I think)
        # so we just reset our date
        self.last_snapshot_time = None

    # don't increment count is silly, but it's to handle the case that we need
    # to take multiple snapshots based on the datetime by replaying the same log,
    # and in that case we don't want to increment checks.
    def should_snapshot_line(self, date, dont_increment_count=False):
        def handle_checks():
            if self.count is None:
                self.count = 0
                return True

            if dont_increment_count:
                return False

            self.count += 1
            if self.count % self.snapshot_every_n_checks == 0:
                self.count = 0
                return True
            return False

        def handle_seconds():
            if self.last_snapshot_time is None:
                self.last_snapshot_time = date
                return True

            diff = (date - self.last_snapshot_time)
            if diff > self.snapshot_every_i_seconds:
                self.last_snapshot_time += self.snapshot_every_i_seconds
                return True
            return False

        if self.strategy == "checks":
            return handle_checks()
        elif self.strategy == "seconds":
            return handle_seconds()
        elif self.strategy == "both":
            checks = handle_checks()
            seconds = handle_seconds()
            return checks or seconds

def timelapse_command(args):
    check_ffmpeg()
    start = args.start_time
    end_function = args.end
    outfile = args.output
    data_path = args.data_directory

    end, was_relative = end_function(start)

    if was_relative:
        print(f"Spanning {start} to {end}")

    validate_start_and_end_dates(start, end)
    timelapse_strategy = TimelapseStrategy(args.snapshot_every_n_checks, args.snapshot_every_i_seconds)

    dates = date_range(start, end)
    image_count = 0
    start_string = start.strftime("%m/%d %H:%M:%S")
    end_string = end.strftime("%m/%d %H:%M:%S")
    start_seconds = start.timestamp()
    end_seconds = end.timestamp()
    total_seconds = end_seconds - start_seconds

    def percent_progress(time):
        since_start = time.timestamp() - start_seconds
        percent = since_start / total_seconds
        return f"{percent: 7.02%}"

    state = None
    prev_era = None
    with tempfile.TemporaryDirectory() as tmpdirname:
        def generate_img_name(description):
            nonlocal image_count
            image_count += 1
            print(f"\33[2K\rCreating image number {image_count: 9} | {description}", end="")
            img_name = f"img-{image_count:09}.png"
            return os.path.join(tmpdirname, img_name)

        print(f"writing data to {tmpdirname}")
        for date in dates:
            era = get_era_for_date(date)
            if era != prev_era:
                prev_era = era
                # We have new snapshots for each era, most relevant for sunsetting because
                # I wiped the whole grid - need to be careful to load the new snapshot
                # and we also want to reset our "last snapshot time" so that our timelapse
                # doesn't have a bunch of dead time during downtime between eras
                print(f"\nbegin {era} {date}")
                timelapse_strategy.reset_date_for_new_era()
                snapshot = get_snapshot_name_for_date(date, data_path=data_path)
                state = state_of_snapshot(snapshot)
            
            if state is None:
                snapshot = get_snapshot_name_for_date(date, data_path=data_path)
                state = state_of_snapshot(snapshot)
            log_name = get_log_name_for_date(date, data_path=data_path)
            with open(log_name, "r") as f:
                for line in f:
                    state, date, status = apply_line_to_state(state, line, after=start, before=end)
                    if status == "before-first":
                        continue
                    elif status == "past-last":
                        break
                    elif status == "continue":
                        dont_increment_count = False
                        while timelapse_strategy.should_snapshot_line(date, dont_increment_count):
                            current_string = date.strftime("%m/%d %H:%M:%S")
                            progress = percent_progress(date)
                            description = f"{progress} ({start_string} | {current_string} | {end_string})"
                            image_of_state(state, generate_img_name(description))
                            dont_increment_count = True
                    else:
                        raise Exception(f"unrecognized status {status}")

        image_of_state(state, generate_img_name("FINAL IMAGE"))
        print()
        print("creating video...")
        video_of_images(tmpdirname, outfile)
        print(f"created {outfile}")

def heatmap_command(args):
    check_ffmpeg()
    start = args.start_time
    end_function = args.end
    outfile = args.output
    data_path = args.data_directory

    end, was_relative = end_function(start)

    if was_relative:
        print(f"Spanning {start} to {end}")

    validate_start_and_end_dates(start, end)
    timelapse_strategy = TimelapseStrategy(args.snapshot_every_n_checks, args.snapshot_every_i_seconds)

    dates = date_range(start, end)
    image_count = 0
    start_string = start.strftime("%m/%d %H:%M:%S")
    end_string = end.strftime("%m/%d %H:%M:%S")
    start_seconds = start.timestamp()
    end_seconds = end.timestamp()
    total_seconds = end_seconds - start_seconds

    def percent_progress(time):
        since_start = time.timestamp() - start_seconds
        percent = since_start / total_seconds
        return f"{percent: 7.02%}"

    state = None
    prev_era = None
    tmpdirname = "./"

    print(f"writing data to {tmpdirname}")
    diff = blank_int_snapshot()
    try:
        snapshot = get_snapshot_name_for_date(dates[0], data_path=data_path)
        old = state_of_snapshot(snapshot) # initialize first diff to no value
    except:
        raise ValueError("Should have at least two states for heatmap mode")
    for date in dates:
        era = get_era_for_date(date)
        if era != prev_era:
            # We have new snapshots for each era, most relevant for sunsetting because
            # I wiped the whole grid - need to be careful to load the new snapshot
            # and we also want to reset our "last snapshot time" so that our timelapse
            # doesn't have a bunch of dead time during downtime between eras
            print(f"\nbegin {era} {date}")
            timelapse_strategy.reset_date_for_new_era()
            snapshot = get_snapshot_name_for_date(date, data_path=data_path)
            state = state_of_snapshot(snapshot)
            diff = add_to_snapshot(state, old, diff)
            old = state
        if state is None:
            snapshot = get_snapshot_name_for_date(date, data_path=data_path)
            state = state_of_snapshot(snapshot)
            diff = add_to_snapshot(state, old, diff)
            old = state
        log_name = get_log_name_for_date(date, data_path=data_path)
        with open(log_name, "r") as f:
                for line in f:
                    state, date, status = apply_line_to_state_heatmap(state, line, after=start, before=end)
                    if status == "before-first":
                        continue
                    elif status == "past-last":
                        break
                    elif status == "continue":
                        dont_increment_count = False
                        while timelapse_strategy.should_snapshot_line(date, dont_increment_count):
                            current_string = date.strftime("%m/%d %H:%M:%S")
                            progress = percent_progress(date)
                            description = f"{progress} ({start_string} | {current_string} | {end_string})"
                            print("\33[2K\r" + description, end="")
                            state = state_of_snapshot(snapshot)
                            diff = add_to_snapshot(state, old, diff)
                            old = state
                            dont_increment_count = True
                    else:
                        raise Exception(f"unrecognized status {status}")
    print()
    image_of_heatmap(diff, outfile, args.logarithmic)
    print("heatmap at", outfile)

def image_at_time_command(args):
    check_ffmpeg()
    date = args.datetime
    outfile = args.output
    data_path = args.data_directory

    within_range_where_site_was_up_exn(date)
    if "." not in outfile:
        outfile += ".png"

    era = get_era_for_date(date)
    snapshot = get_snapshot_name_for_date(date, data_path=data_path)
    log_name = get_log_name_for_date(date, data_path=data_path)

    state = state_of_snapshot(snapshot)
    state = apply_logs_to_state(state, log_name, date)
    image_of_state(state, outfile)
    print(f"created {outfile}")

def parse_datetime(s):
    if not s.endswith("Z") and "+" not in s:
        s += "Z"
    try:
        return isodate(s)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid datetime format: {s}")

def parse_datetime_or_span(s):
    try:
        t = s.lower()
        if t.endswith("h"):
            t = t[:-1]
        hours = float(t)
        def ret(start):
            delta = datetime.timedelta(hours=hours)
            return (start + delta, True)
        return ret
    except ValueError:
        v = parse_datetime(s)
        def ret(_start):
            return (v, False)
        return ret

def main():
    parser = argparse.ArgumentParser(description="Interact with omcb data")

    subparsers = parser.add_subparsers(title="commands", dest="command")

    state_at_time = subparsers.add_parser("state-at-time", help="Get state at a given time")
    state_at_time.add_argument("datetime", type=parse_datetime, help="Datetime in ISO format (YYYY-MM-DDTHH:MM:SS)")
    state_at_time.add_argument("--data-directory", required=False, help="Path to directory where OMCB data is, if it's not in the standard location (default - a directory named 'omcb-data' that is a sibling of the 'scripts' dir that this script lives in")
    state_at_time.add_argument("-o", "--output", help="Output filename")
    state_at_time.set_defaults(func=state_at_time_command)

    image_at_time = subparsers.add_parser("image-at-time", help="Get an image at a given time (requires ffmpeg)")
    image_at_time.add_argument("--data-directory", required=False, help="Path to directory where OMCB data is, if it's not in the standard location (default - a directory named 'omcb-data' that is a sibling of the 'scripts' dir that this script lives in")
    image_at_time.add_argument("datetime", type=parse_datetime, help="Datetime in ISO format (YYYY-MM-DDTHH:MM:SS)")
    image_at_time.add_argument("-o", "--output", help="Output filename")
    image_at_time.set_defaults(func=image_at_time_command)

    timelapse = subparsers.add_parser("timelapse", help="Create an image timelapse for a timerange (requires ffmpeg)")
    timelapse.add_argument("start_time", type=parse_datetime, help="Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS)")
    timelapse.add_argument("end", type=parse_datetime_or_span, help="End - either a timespan in hours, or a datetime in ISO format (YYYY-MM-DDTHH:MM:SS)")
    timelapse.add_argument("--data-directory", required=False, help="Path to directory where OMCB data is, if it's not in the standard location (default - a directory named 'omcb-data' that is a sibling of the 'scripts' dir that this script lives in")
    timelapse.add_argument("-o", "--output", required=True, help="Output filename")
    timelapse.add_argument("-n", "--snapshot-every-n-checks", type=int, required=False, default=None, help="Create a snapshot for every n checks. Can be combined with -i (will snapshot whenever either happens)")
    timelapse.add_argument("-i", "--snapshot-every-i-seconds", type=int, required=False, default=DefaultValue(5), help="Create a snapshot every i seconds. Can be combined with -n (will snapshot whenever either happens)")
    timelapse.set_defaults(func=timelapse_command)
    
    heatmap = subparsers.add_parser("heatmap", help="Create an image heatmap for a timerange (requires ffmpeg)")
    heatmap.add_argument("start_time", type=parse_datetime, help="Start datetime in ISO format (YYYY-MM-DDTHH:MM:SS)")
    heatmap.add_argument("end", type=parse_datetime_or_span, help="End - either a timespan in hours, or a datetime in ISO format (YYYY-MM-DDTHH:MM:SS)")
    heatmap.add_argument("--data-directory", required=False, help="Path to directory where OMCB data is, if it's not in the standard location (default - a directory named 'omcb-data' that is a sibling of the 'scripts' dir that this script lives in")
    heatmap.add_argument("-n", "--snapshot-every-n-checks", type=int, required=False, default=None, help="Create a snapshot for every n checks. Can be combined with -i (will snapshot whenever either happens)")
    heatmap.add_argument("-o", "--output", required=True, help="Output filename. Should be pillow compatible")
    heatmap.add_argument("-i", "--snapshot-every-i-seconds", type=int, required=False, default=DefaultValue(5), help="Create a snapshot every i seconds. Can be combined with -n (will snapshot whenever either happens)")
    heatmap.add_argument("-l", "--logarithmic", type=int, required=False, default=0, help="Scale of logarithmic function (0 for linear, defaults to 0. Negative values become 0)")
    heatmap.set_defaults(func=heatmap_command)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
