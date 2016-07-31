#!/usr/bin/python
# Usage: python videoCheck.py --videoid=<video_id>

import httplib2
import sys

from apiclient.discovery import build_from_document
from apiclient.errors import HttpError
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client.tools import argparser, run_flow
from Queue import Queue


# # # # # # # # #
# AUTHORIZATION #
# # # # # # # # #

CLIENT_SECRETS_FILE = "secrets/client_secrets.json"
DEVELOPER_SECRETS_FILE = "secrets/youtube-v3-discoverydocument.json"
YOUTUBE_READ_WRITE_SSL_SCOPE = "https://www.googleapis.com/auth/youtube.force-ssl"
YOUTUBE_API_SERVICE_NAME = "youtube"
YOUTUBE_API_VERSION = "v3"


def get_authenticated_service(args):
    flow = flow_from_clientsecrets(CLIENT_SECRETS_FILE, scope=YOUTUBE_READ_WRITE_SSL_SCOPE,
                                   message="Invalid client secrets file.")
    storage = Storage("%s-oauth2.json" % sys.argv[0])
    credentials = storage.get()

    if credentials is None or credentials.invalid:
        credentials = run_flow(flow, storage, args)

    with open(DEVELOPER_SECRETS_FILE, "r") as f:
        doc = f.read()
    return build_from_document(doc, http=credentials.authorize(httplib2.Http()))


# # # # # # #
# ALGORITHM #
# # # # # # #

ENCODING = "utf-8"
NUM_RELATED_VIDEOS = 10
NUM_COMMENTS_PER_PAGE = 100
NUM_COMMENT_PAGES = 10
WEIRD_INDICATORS = [
                    ["weird", "part", "of"], ["wierd", "part", "of"], ["that's enough internet"], ["enough for today"],
                    ["how", "did i get here"], ["what", "did", "i just watch"], ["the fuck did i", "watch"],
                    ["i'm in hell"], ["im in hell"], ["why", "what", "am i watching"]
                   ]


def setup_args():
    argparser.add_argument("--videoid", help="Required; ID for video.")
    argparser.add_argument("--debug", help="Prints all video comments read.", action="store_true")
    argparser.add_argument("--showreason", help="Prints comment that classifies video as weird.", action="store_true")
    args = argparser.parse_args()
    if not args.videoid:
        exit("Please specify videoid using the --videoid= parameter.")
    return args

def get_video_title(youtube, args):
    video_response = youtube.videos().list(
        part='snippet',
        id=args.videoid
    ).execute()
    video = video_response.get("items", [])[0]
    return str(video["snippet"]["title"])


def get_first_video(youtube, args):
    return {"videoid": args.videoid, "title": get_video_title(youtube, args), "previd": None, "clicks":0}


def is_weird(author, comment, args):
    lowercase_comment = comment.lower()
    for indicator_list in WEIRD_INDICATORS:
        if all(token in lowercase_comment for token in indicator_list):
            if args.showreason:
                print('REASON: ' + author.encode(ENCODING) + ': "' + comment.encode(ENCODING) +
                      '" had a derivation of ' + str(indicator_list)[1:-1])
            return True
    return False


def is_video_weird(youtube, args, video):
    next_page_token = None
    for i in range(0, NUM_COMMENT_PAGES):
        results = youtube.commentThreads().list(
            part="snippet",
            videoId=video["videoid"],
            textFormat="plainText",
            maxResults=NUM_COMMENTS_PER_PAGE,
            pageToken=next_page_token
        ).execute()

        for item in results["items"]:
            comment = item["snippet"]["topLevelComment"]
            author = comment["snippet"]["authorDisplayName"]
            text = comment["snippet"]["textDisplay"]
            if is_weird(author, text, args):
                return True

        if "nextPageToken" in results:
            next_page_token = results["nextPageToken"]
        else:
            break
    return False


def get_related_videos(youtube, args, prev_video):
    search_response = youtube.search().list(
        part="snippet",
        type="video",
        maxResults=NUM_RELATED_VIDEOS,
        relatedToVideoId=prev_video["videoid"]
    ).execute()

    related_videos = []
    for search_result in search_response.get("items", []):
        if search_result["id"]["kind"] == "youtube#video":
            related_videos.append({
                "videoid": search_result["id"]["videoId"],
                "title": search_result["snippet"]["title"],
                "previd": prev_video["videoid"],
                "clicks": prev_video["clicks"] + 1
            })
    return related_videos


def check_weirdness(youtube, args, video):
    if is_video_weird(youtube, args, video):
        return None
    else:
        return get_related_videos(youtube, args, video)


def reconstruct_path(video, visited_videos):
    path = [video]
    previd = video["previd"]
    while previd is not None:
        next_video = visited_videos[previd]
        path.append(next_video)
        previd = next_video["previd"]

    reconstructed_path = ""
    index = 1
    for video in reversed(path):
        reconstructed_path += str(index) + ". " + video["title"] + " (http://www.youtube.com/watch?v=" +\
                              video["videoid"] + ") ->\n"
        index += 1
    return reconstructed_path[:-4]


def main():
    # Setup
    args = setup_args()
    youtube = get_authenticated_service(args)

    # Visible metadata
    queue = Queue()
    visited_videos = {}
    highest_clicks = 0

    if args.debug:
        print("DEBUG: Arguments: " + str(args))

    print("================")
    print("BEGINNING SEARCH")
    print("================")
    video = get_first_video(youtube, args)
    print("Checking initial video...")

    # Wrap requests
    try:
        queue.put(video)
        visited_videos[video["videoid"]] = video

        while not queue.empty():
            # Get next video in queue
            video = queue.get()

            if args.debug:
                print("DEBUG: Trying " + video["title"] + " (http://www.youtube.com/watch?v=" +
                      video["videoid"] + ") " + str(video["clicks"]) + " click(s) away.")

            # Show realtime progress by directly writing to output if no debug prints will disrupt
            if video["clicks"] > highest_clicks:
                highest_clicks = video["clicks"]
                sys.stdout.write("\nChecking videos " + str(highest_clicks) + " click(s) away...")
            elif not args.debug and highest_clicks > 0:
                sys.stdout.write(".")


            # Get related videos
            related_videos = check_weirdness(youtube, args, video)
            if related_videos is None:
                break
            for related_video in related_videos:
                prev_queue_size = queue.qsize()
                if related_video["videoid"] not in visited_videos:
                    visited_videos[related_video["videoid"]] = related_video
                    queue.put(related_video)


    except HttpError, e:
        print("An HTTP error " + str(e.resp.status) + " occurred: " + str(e))

    # Process and print results
    print
    print("=======")
    print("RESULTS")
    print("=======")
    print("Reached the weird part of YouTube: " + video["title"] + " in " + str(video["clicks"]) + " click(s).")

    path = reconstruct_path(video, visited_videos)

    print
    print("====")
    print("PATH")
    print("====")
    print(path)


if __name__ == "__main__":
    main()