#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
import re
import errno
from os import path, strerror
from glob import glob
import subprocess
import threading
import rumps
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


APP_VERSION = 20220106
APP_NAME = "ComMute for Spotify"


class ComMuteApp(rumps.App):

    def __init__(self):

        super().__init__(APP_NAME)  # ComMuteApp, self

        self.icon = 'res/app_normal.png'
        self.template = True
        self.quit_button = None
        self.menu = []
        self.update_menu()

    def update_menu(self):

        np = current['str']
        if len(np) > 40:
            np = np[:35]+'…'

        playpause = rumps.MenuItem(" Play / pause", icon="res/icon_play.png",
                                   dimensions=(16, 16),
                                   template=True,
                                   callback=play_pause)

        nowplaying = rumps.MenuItem(" "+np, icon="res/icon_music.png",
                                    dimensions=(16, 16),
                                    template=True,
                                    callback=self.copy_url)

        ad_slider = rumps.SliderMenuItem(value=current['advol'],
                                         min_value=0,
                                         max_value=100,
                                         callback=self.update_ad_slider)

        song_slider = rumps.SliderMenuItem(value=current['songvol'],
                                           min_value=0,
                                           max_value=100,
                                           callback=self.update_track_slider)

        self.menu.clear()
        self.menu = [f"{APP_NAME} {APP_VERSION}",
                     None,
                     playpause,
                     nowplaying,
                     [rumps.MenuItem(" Volume", icon="res/icon_empty.png", dimensions=(16, 16)), [
                         "Ad volume:",
                         ad_slider,
                         None,
                         "Song volume:",
                         song_slider]],
                     None,
                     rumps.MenuItem(" Quit", icon="res/icon_empty.png", dimensions=(16, 16), callback=self.quit_app)]

    @staticmethod
    def copy_url(_):
        text = current['str'] + '\n' + current['url']
        process = subprocess.Popen('pbcopy', env={'LANG': 'en_US.UTF-8'}, stdin=subprocess.PIPE)
        process.communicate(text.encode('utf-8'))
        rumps.notification("copied track & URL to clipboard", current['str'], current['url'], sound=False)

    @staticmethod
    def update_ad_slider(sender):
        if current['advol'] != int(sender.value):
            current['advol'] = max(int(sender.value), 15)  # don't set volume below 15; Spotify will stop playing
            sender.value = current['advol']
            if current['ad']:
                set_volume(current['advol'])

    @staticmethod
    def update_track_slider(sender):
        if current['songvol'] != int(sender.value):
            current['songvol'] = int(sender.value)
            if not current['ad']:
                set_volume(current['songvol'])

    @staticmethod
    def quit_app(_):
        print('quitting')
        save_config([current['watchfile'], current['advol'], current['songvol']])
        rumps.quit_application()


def load_config():
    filename = path.expanduser('~/.config/ComMute.conf')
    try:
        with open(filename, 'r') as file:
            watchfile, advol, songvol = file.read().strip().split('\n')
            advol = int(advol)
            songvol = int(songvol)

    except BaseException:
        sfy_user_dirs = glob(path.expanduser("~")+'/Library/Application Support/Spotify/Users/*')
        if len(sfy_user_dirs) == 0:
            raise FileNotFoundError(errno.ENOENT, strerror(errno.ENOENT), '~/Library/Application Support/Spotify/Users/*/')
        watchfile = sfy_user_dirs[0] + '/ad-state-storage.bnk.tmp'
        advol = 50
        songvol = 100

    return({'watchfile': watchfile, 'advol': advol, 'songvol': songvol})


def save_config(config):
    filename = path.expanduser('~/.config/ComMute.conf')
    with open(filename, 'w') as file:
        file.writelines([str(x)+'\n' for x in config])


# function to run applescript, returns output as UTF-8
def run_applescript(script):

    command = ['osascript', '-e', script]

    out = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    stdout, stderr = out.communicate()

    if stderr:
        print(stdout)
        raise RuntimeError(stderr)

    return stdout.decode('UTF-8')


# function to play/pause Spotify
def play_pause(_):

    script = '''
    tell application "Spotify"
        playpause
    end tell
    '''

    run_applescript(script)


# function to get ad status from Spotify, returns True / False on success, False on error
def get_ad_status():

    # get id
    script = '''
    tell application "Spotify"
        return id of the current track
    end tell
    '''
    r = run_applescript(script)

    try:
        ad = r[:11] == 'spotify:ad:'
    except IndexError:
        ad = False

    # return
    return ad


# function to get current volume from Spotify, returns volume 0..100 on success, False on error
def get_volume():

    script = '''
    tell application "Spotify"
        return sound volume
    end tell
    '''
    r = run_applescript(script)
    r = r.strip()

    try:
        r = int(r)
    except ValueError:
        r = False

    return r


# function to set current volume in Spotify, returns nothing
def set_volume(volume):

    script = f'''
    tell application "Spotify"
        set sound volume to {volume}
    end tell
    '''
    run_applescript(script)


def get_track_info():

    script = '''
    tell application "Spotify"
        set c to the current track
        return {sound volume, id of c, artist of c, name of c}
    end tell
    '''

    info = {}

    try:
        r = run_applescript(script)
        r = r.split(',', 2)
        r = [x.strip() for x in r]

        info['vol'] = int(r[0])

        info['ad'] = r[1][:11] == 'spotify:ad:'

        if info['ad']:
            info['str'] = '(advertisement)'
        else:
            info['str'] = r[2]

        r = re.search('spotify:(.*):(.*)', r[1])
        info['url'] = f'http://open.spotify.com/{r.group(1)}/{r.group(2)}'

    except BaseException:
        print("Error fetching track info from Spotify")
        return {'ad': False, 'ok': False}

    info['ok'] = True
    print('; '.join([f'{k}: {v}'for k, v in info.items()]))
    return info


def watchdog():

    # start watchdog for newly created files in WatchFile's parent directory
    watchdog_event_handler = FileSystemEventHandler()
    watchdog_event_handler.on_created = watchdog_on_created_event
    watchdog_observer = Observer()
    watchdog_observer.schedule(watchdog_event_handler, path=path.dirname(current['watchfile']), recursive=False)
    watchdog_observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        watchdog_observer.stop()
        watchdog_observer.join()


# function triggered when a file is changed in our watchdir
def watchdog_on_created_event(event):

    # check if our watchfile is the trigger and we're not still working on the last trigger
    if event.src_path == current['watchfile'] and not current['event_lock']:

        # prevent the next watchdog_event from running during this one
        current['event_lock'] = True

        # give some output to CLI
        print('[{}] watchdog event'.format(time.strftime("%H:%M:%S", time.localtime())))

        # get current info
        track = get_track_info()

        # if we're currently listening to an ad, and one wasn't playing before, set Spotify volume = ad_volume
        if track['ad']:
            if not current['ad_was_playing']:
                set_volume(current['advol'])
                print(f'🔇 set spotify volume: {current["advol"]}')
                current['ad_was_playing'] = True
                app.icon = 'res/app_muted.png'
            else:
                print('🔇 ad continues')

        # if we're currently listening to a song, but an ad was playing before, set Spotify volume = song_volume
        elif current['ad_was_playing']:
            set_volume(current['songvol'])
            print(f'🔊 set spotify volume: {current["songvol"]}')
            current['ad_was_playing'] = False
            app.icon = 'res/app_normal.png'

        # if we're listening to a song, and we were before as well
        else:
            # update song_volume setting with current Spotify volume
            if track['ok']:
                print(f'🔊 update songvol setting: {track["vol"]}')
                current['songvol'] = track['vol']

        # update `current` and menubar app
        if track['ok']:
            need_to_update_menu = current['str'] != track['str']
            current.update(track)
            if need_to_update_menu:
                app.update_menu()

        # unlock for next event
        current['event_lock'] = False

        print()


if __name__ == '__main__':

    # load defaults and settings
    current = {'ad': False, 'str': '<unable to communicate with Spotify>',
               'url': 'https://github.com/cwverhey/ComMute/',
               'watchfile': False, 'vol': 100, 'advol': False, 'songvol': False,
               'ad_was_playing': False, 'event_lock': False}
    current.update(load_config())

    # create menu bar mini app
    app = ComMuteApp()

    # update current song info
    track = get_track_info()
    if track['ok']:
        current.update(track)
        app.update_menu()
    print()

    # start watchdog (updates volume and song info on track change)
    x = threading.Thread(target=watchdog)
    x.start()

    # start app
    app.run()
