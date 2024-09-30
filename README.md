# Scripts for working with data from One Million Checkboxes
_This data is licensed under the Creative Commons BY-SA (CC-BY-SA) license. See LICENSE for more details._

This repo contains code for generating images, timelapses, and heatmaps from the data for [One Million Checkboxes](https://en.wikipedia.org/wiki/One_Million_Checkboxes). [A separate download](https://archive.org/details/one-million-checkboxes-data) contains the (large!) dataset that these tools are designed to work with.

Some of those timelapses look like this:

![rick2](https://github.com/user-attachments/assets/f63ee150-d863-462b-a094-e9a64c01e63e)


## What was One Million Checkboxes?
One Million Checkboxes (OMCB) was a website released on June 26, 2024 that had a million checkboxes on it. The checkboxes were global - checking or unchecking a box checked or unchecked it for everyone on the site.

The site was live for 2 weeks. In those two weeks, hundreds of thousands of players checked or unchecked more than 650,000,000 checkboxes.

## Why a timelapse tool?
As documented [here](https://eieio.games/essays/the-secret-in-one-million-checkboxes/), within a few days of launch users began to hide images and links in the state of OMCB. Most images were drawn on a monochrome hypothetical 1000x1000 canvas where unchecked boxes were treated as black and checked boxes were treated as white.

Additionally, users wrote secret messages in binary (visible by converting OMCB's binary state to ascii) and base64 (viewable when fetching the data on the site, since data was transported in base64).

So in addition to letting you visualize which boxes were checked over time, the timelapse tool lets you see the images that users drew.

## Where do I get the data?
The data is hosted on the Internet Archive. You can download it [here](https://archive.org/details/one-million-checkboxes-data).

## Once I've downloaded the data what should I do with it?
Extract the data to a directory named `omcb-data`. Then place it in the same parent directory as this repository. Things should automatically work.

That means that your directory layout should look like this:
* `parent-dir`
* `parent-dir/this-repo`
* `parent-dir/omcb-data`

Alternatively, you can manually specify the path to the data directory with the `--data-directory` argument

## How do I use this code?
First, download the data (again, the link is [here](https://archive.org/details/one-million-checkboxes-data)). If you want to look at it manually, just extract the archive and poke around.

To get set up with the scripts:
1. Install python3 if you don't have it installed
2. Move to the scripts directory
3. Create a python virtual environment (probably you should run `python3 -m venv venv` but this may depend on your python installation and operating system)
4. Source the environment that you created (`source venv/bin/activate`)
5. Install dependencies (`pip install -r requirements.txt`)
6. Run `python omcb.py` with the relevant command

### Timelapse

To generate a timelapse, run

`python omcb.py timelapse START_DATE NUMBER_OF_HOURS -o VIDEOFILE.mp4 -i NUMBER_OF_SECONDS_PER_FRAME`

Or if you'd rather manually specify the end date

`python omcb.py timelapse START_DATE END_DATE -o VIDEOFILE.mp4 -i NUMBER_OF_SECONDS_PER_FRAME`

For example

`python ./omcb.py timelapse 2024-07-11T16:30:01Z 0.5h -o example.mp4 -i 5`

Will generate a 30 minute timelapse named `example.mp4` starting at 2024-07-11T16:30:01, with a frame every 5 seconds

And 

`python ./omcb.py timelapse 2024-07-04T00:30:00Z 2024-07-05T00:30:00Z -o example.mp4 -i 30`

Will generate a timelapse from 2024-07-04T00:30:00 to 2024-07-05T00:30:00, with a frame every 30 seconds.

### Heatmap

To generate a heatmap, run

`python omcb.py timelapse START_DATE NUMBER_OF_HOURS -o IMAGEFILE.png -i NUMBER_OF_SECONDS_PER_DIFF_SAMPLE -l LOGARITHMIC_SCALE`

For example

`python ./omcb.py heatmap 2024-07-04T00:30:00Z 2024-07-05T00:30:00Z -o example.png -i 5`

Will generate a heatmap for 2024-07-04T00:30:00 to 2024-07-05T00:30:00, with a difference sampled every 5 seconds.

## Data description and caveats
[The archive](https://archive.org/details/one-million-checkboxes-data) is missing data from the first several hours after OMCB was launched. I (the creator of the site) am sorry about that! I was originally only keeping the first 1 million logs over the course of the day under the assumption that anything beyond that would indicate a bug. I failed to anticipate the popularity of the site!

I also lost some data every time the site crashed or I bounced a server. So it's definitely incomplete (and it's hard to quantify exactly how incomplete), but hopefully good enough in practice. You may see redundant checks, and the "final" version of the data doesn't end with every box checked due to lost data. Sorry.

The data is also split into 3 different "eras"

1. `pre-crash`: The first day of the site, from when we begin having data to a major crash about 20 hours after the site went live. The site was down for several hours and I had to manually reconstruct some of its state.
2. `post-crash-pre-sunset`: The second day of the site until the time when I began shutting down the site.
3. `post-sunset`: The final hours of the site. I wiped the state and made boxes "freeze" as checked if they weren't unchecked quickly, eventually resulting in all boxes being checked.

We split the data into eras to know which initial state value to load (the timelapse tool works by loading some state and then playing logs over it to compute the state at a moment in time). If you're working with the data outside of the tool be careful to account for these eras.

Data is located in subdirectories of the `omcb-data` directory; each subdirectory uses one of the era names above. Those era directories contain `.log` files with all of the check events for a given day. There are also "snapshot" files that contain binary blobs of the state at different moments in time. `initial.db` represents the state at the start of the era, `final.db` represents the state at the end of the era, and the dated `.db` files represent the state at the start of that day. The provided tooling automatically references these files.

`.log` files are pipe (|) separated ascii text files. The format is `TIME|BOX_NUMBER|CHECK_OR_UNCHECK` - e.g. `2024-06-26T19:00:40|75|1` means that box 75 was checked (1) on 2024-06-26T19:00:40, and `2024-06-26T19:00:43|3242|0` means that box 3242 was unchecked (0) at 2024-06-26T19:00:43. Times are in UTC.

