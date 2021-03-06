# coding: utf-8
"""
Display information from mpd.

Configuration parameters:
    cache_timeout = how often we refresh this module in seconds (2s default)
    color = enable coloring output (default False)
    color_pause = custom pause color (default i3status color degraded)
    color_play = custom play color (default i3status color good)
    color_stop = custom stop color (default i3status color bad)
    format = template string (see below)
    hide_when_paused: hide the status if state is paused
    hide_when_stopped: hide the status if state is stopped
    host: mpd host
    max_width: maximum status length
    password: mpd password
    port: mpd port
    state_pause: label to display for "paused" state
    state_play: label to display for "playing" state
    state_stop: label to display for "stopped" state

Requires:
    - python-mpd2 (NOT python2-mpd2)
    # pip install python-mpd2

Refer to the mpc(1) manual page for the list of available placeholders to be
used in `format`.
You can also use the %state% placeholder, that will be replaced with the state
label (play, pause or stop).
Every placeholder can also be prefixed with `next_` to retrieve the data for
the song following the one currently playing.

You can also use {} instead of %% for placeholders (backward compatibility).

Examples of `format`:
    Show state and (artist -) title, if no title fallback to file:
    %state% [[[%artist% - ]%title%]|[%file%]]

    Alternative legacy syntax:
    {state} [[[{artist} - ]{title}]|[{file}]]

    Show state, [duration], title (or file) and next song title (or file):
    %state% \[%time%\] [%title%|%file%] → [%next_title%|%next_file%]

@author shadowprince
@author zopieux
@license Eclipse Public License
"""

import ast
import datetime
import itertools
import socket
import time
from mpd import MPDClient, CommandError


def parse_template(instr, value_getter, found=True):
    """
    MPC-like parsing of `instr` using `value_getter` callable to retrieve the
    text representation of placeholders.
    """
    instr = iter(instr)
    ret = []
    for char in instr:
        if char in '%{':
            endchar = '%' if char == '%' else '}'
            key = ''.join(itertools.takewhile(lambda e: e != endchar, instr))
            value = value_getter(key)
            if value:
                found = True
                ret.append(value)
            else:
                found = False
        elif char == '#':
            ret.append(next(instr, '#'))
        elif char == '\\':
            ln = next(instr, '\\')
            if ln in 'abtnvfr':
                ret.append(ast.literal_eval('"\\{}"'.format(ln)))
            else:
                ret.append(ln)
        elif char == '[':
            subret, found = parse_template(instr, value_getter, found)
            subret = ''.join(subret)
            ret.append(subret)
        elif char == ']':
            if found:
                ret = ''.join(ret)
                return ret, True
            else:
                return '', False
        elif char == '|':
            subret, subfound = parse_template(instr, value_getter, found)
            if found:
                pass
            elif subfound:
                ret.append(''.join(subret))
                found = True
            else:
                return '', False
        elif char == '&':
            subret, subfound = parse_template(instr, value_getter, found)
            if found and subfound:
                subret = ''.join(subret)
                ret.append(subret)
            else:
                return '', False
        else:
            ret.append(char)

    ret = ''.join(ret)
    return ret, found


def song_attr(song, attr):
    def parse_mtime(date_str):
        return datetime.datetime.strptime(date_str, '%Y-%m-%dT%H:%M:%SZ')

    if attr == 'time':
        try:
            duration = int(song['time'])
            if duration > 0:
                minutes, seconds = divmod(duration, 60)
                return '{:d}:{:02d}'.format(minutes, seconds)
            raise ValueError
        except (KeyError, ValueError):
            return ''
    elif attr == 'position':
        try:
            return '{}'.format(int(song['pos']) + 1)
        except (KeyError, ValueError):
            return ''
    elif attr == 'mtime':
        return parse_mtime(song['last-modified']).strftime('%c')
    elif attr == 'mdate':
        return parse_mtime(song['last-modified']).strftime('%x')

    return song.get(attr, '')


class Py3status:
    """
    """
    # available configuration parameters
    cache_timeout = 2
    color = False
    color_pause = None
    color_play = None
    color_stop = None
    format = '%state% [[[%artist%] - %title%]|[%file%]]'
    hide_when_paused = False
    hide_when_stopped = True
    host = 'localhost'
    max_width = 120
    password = None
    port = '6600'
    state_pause = '[pause]'
    state_play = '[play]'
    state_stop = '[stop]'

    def __init__(self):
        self.text = ''

    def _state_character(self, state):
        if state == 'play':
            return self.state_play
        elif state == 'pause':
            return self.state_pause
        elif state == 'stop':
            return self.state_stop
        return '?'

    def current_track(self, i3s_output_list, i3s_config):
        try:
            c = MPDClient()
            c.connect(host=self.host, port=self.port)
            if self.password:
                c.password(self.password)

            status = c.status()
            song = int(status.get('song', 0))
            next_song = int(status.get('nextsong', 0))

            state = status.get('state')

            if ((state == 'pause' and self.hide_when_paused) or
                (state == 'stop' and self.hide_when_stopped)):
                text = ''

            else:
                playlist_info = c.playlistinfo()
                try:
                    song = playlist_info[song]
                except IndexError:
                    song = {}
                try:
                    next_song = playlist_info[next_song]
                except IndexError:
                    next_song = {}

                song['state'] = next_song['state'] \
                              = self._state_character(state)

                def attr_getter(attr):
                    if attr.startswith('next_'):
                        return song_attr(next_song, attr[5:])
                    return song_attr(song, attr)

                text, _ = parse_template(self.format, attr_getter)

        except socket.error:
            text = "Failed to connect to mpd!"
        except CommandError:
            text = "Failed to authenticate to mpd!"
            c.disconnect()

        if len(text) > self.max_width:
            text = text[:-self.max_width - 3] + '...'

        if self.text != text:
            transformed = True
            self.text = text
        else:
            transformed = False

        response = {
            'cached_until': time.time() + self.cache_timeout,
            'full_text': self.text,
            'transformed': transformed
        }

        if self.color:
            if state == 'play':
                response['color'] = self.color_play or i3s_config['color_good']
            elif state == 'pause':
                response['color'] = (self.color_pause
                                     or i3s_config['color_degraded'])
            elif state == 'stop':
                response['color'] = self.color_stop or i3s_config['color_bad']

        return response


if __name__ == "__main__":
    """
    Test this module by calling it directly.
    """
    from time import sleep
    x = Py3status()

    config = {
        'color_bad': '#FF0000',
        'color_degraded': '#FFFF00',
        'color_good': '#00FF00'
    }
    while True:
        print(x.current_track([], config))
        sleep(1)
