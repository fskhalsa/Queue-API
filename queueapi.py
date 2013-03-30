import datetime
import json

from flask import Flask, request
from flask.ext.restful import Resource, Api

import requests

from queue import app, api, db

from models import SongItem, User, Artist, Album, Friend, ArtistItem, NoteItem

LF_API_URL = app.config['LF_API_URL']
LF_API_KEY = app.config['LF_API_KEY']
FB_API_URL = app.config['FB_API_URL']

def fix_lastfm_listens_data(data):
    data['recenttracks'][u'metadata'] = data['recenttracks'].pop('@attr')
    data['recenttracks'][u'tracks'] = data['recenttracks'].pop('track')

    for i, track in enumerate(data['recenttracks']['tracks']):

        track['album'][u'name'] = track['album'].pop('#text')
        track['streamable'] = int(track['streamable'])
        track['loved'] = int(track['loved'])

        del track['artist']['url']

        if track.has_key("date"):
            del track['date']['#text']
            track.update(track["date"])
            del track['date']

        if track.has_key("@attr"):
            track['nowplaying'] = True
            del track["@attr"]

    fix_image_data(track)
    fix_image_data(track['artist'])

    return data

def fix_image_data(data):
    if 'image' in data:
        data['images'] = {}
        print data
        for image in data['image']:
            data['images'][image['size']] = image.pop('#text')

        del data['image']


def fix_lf_track_search(data):
    fix_search_metadata(data)
    data['tracks'] = data.pop('trackmatches')['track']
    del data['@attr']

    for track in data['tracks']:
        fix_image_data(track)
        del track['streamable']
        del track['url']

    return data


def fix_lf_artist_search(data):
    fix_search_metadata(data)
    data['artists'] = data.pop('artistmatches')['artist']
    del data['@attr']

    for artist in data['artists']:
        fix_image_data(artist)
        del artist['streamable']
        del artist['url']

    return data

def fix_search_metadata(data):
    data['metadata'] = {}
    data['metadata']['opensearch:Query'] = data.pop('opensearch:Query')
    data['metadata']['opensearch:totalResults'] = data.pop('opensearch:totalResults')
    data['metadata']['opensearch:startIndex'] = data.pop('opensearch:startIndex')
    data['metadata']['opensearch:itemsPerPage'] = data.pop('opensearch:itemsPerPage')


class Search(Resource):
    def get(self, search_text):
        search_url = "%smethod=track.search&track=%s&api_key=%sformat=json"
        track_results = requests.get(search_url %
                        (LF_API_URL, search_text, LF_API_KEY)).json()['results']

        search_url = "%smethod=artist.search&artist=%s&api_key=%sformat=json"
        artist_results = requests.get(search_url %
                        (LF_API_URL, search_text, LF_API_KEY)).json()['results']

        results = {'track_results':fix_lf_track_search(track_results),
                   'artist_results':fix_lf_artist_search(artist_results)}

        return results

class Listens(Resource):
    def get(self, user_name):
        data = requests.get("%smethod=user.getrecenttracks&user=%s&api_key=%sformat=json&extended=1"
                            % (LF_API_URL, user_name, LF_API_KEY)).json()
        return fix_lastfm_listens_data(data)


class Friends(Resource):
    def get(self, user_name):
        args = request.values
        access_token = args['access_token']
        user = get_user(user_name)

        if not user:
            return no_such_user(user_name)

        friends = []
        for friend in db.session.query(Friend).filter(Friend.user_id == user.id):
            friends.append(friend.dictify())

        return friends

class UserAPI(Resource):
    def post(self, user_name):
        args = request.json
        access_token = args['access_token']
        default = args['default']
        fb_id = args['fb_id']
        resp = requests.get("%s/%s/friends?limit=5000&access_token=%s" %
                                (FB_API_URL, fb_id, access_token))
        if 'data' not in resp.json():
            pass
            #return {"status":500, "message": 'problem getting friends'}

        #friends = resp.json()['data']
        friends = []
        user = User(user_name, access_token)
        for friend in friends:
            f = Friend(friend['name'], friend['id'], user)
            db.session.add(f)

        db.session.add(user)
        db.session.commit()

        return {"status":"OK"}


class Queue(Resource):
    def get(self, user_name):

        user = get_user(user_name)

        if not user:
            return no_such_user(user_name)

        songs = db.session.query(SongItem)\
            .filter(SongItem.user_id == user.id).all()
        artists = db.session.query(ArtistItem)\
            .filter(ArtistItem.user_id == user.id).all()
        notes = db.session.query(NoteItem)\
            .filter(NoteItem.user_id == user.id).all()

        orm_queue = songs + artists + notes
        queue = []
        for orm_item in orm_queue:
            queue.append(orm_item.dictify())

        queue = sorted(queue, key=lambda x: (x['listened'], -1*x['date_queued']))
        return {"queue":queue}

    def post(self, user_name):

        args = request.json
        access_token = args['access_token']
        item = args['item']
        from_user_name = args['from_user_name']

        from_user = get_user(from_user_name)
        to_user = get_user(user_name)

        if not from_user:
            return no_such_user(from_user)

        if not to_user:
            return no_such_user(to_user)

        if not is_friends(from_user, to_user):
           return {'status':400, 'message':'users are not friends'}

        if item['type'] == 'song':
            artist = item['artist']
            orm_artist = Artist(name=artist['name'], mbid=artist['mbid'],
                                small_image_link=artist['images']['small'],
                                medium_image_link=artist['images']['medium'],
                                large_image_link=artist['images']['large'])

            album = item['album']
            orm_album = Album(name=album['name'], mbid=album['mbid'])

            orm_song = SongItem(user=to_user,queued_by_user=from_user,
                            listened=False, name=item['name'],
                            date_queued=datetime.datetime.utcnow(),
                            small_image_link=item['images']['small'],
                                medium_image_link=item['images']['medium'],
                                large_image_link=item['images']['large'])

            orm_song.artist = orm_artist
            orm_song.album = orm_album
            db.session.add(orm_song)
            db.session.add(orm_album)
            db.session.add(orm_artist)

        elif item['type'] == 'artist':
            orm_artist = ArtistItem(user=to_user,queued_by_user=from_user,
                            listened=False, name=item['name'],
                            date_queued=datetime.datetime.utcnow(),
                            small_image_link=item['images']['small'],
                                medium_image_link=item['images']['medium'],
                                large_image_link=item['images']['large'])

            db.session.add(orm_artist)

        elif item['type'] == 'note':
            orm_note = NoteItem(user=to_user,queued_by_user=from_user,
                            listened=False, text=item['text'],
                            date_queued=datetime.datetime.utcnow())

            db.session.add(orm_note)

        db.session.commit()

        return {"status":"OK"}


def get_user(user_name):
    users = list(db.session.query(User).filter(User.uname == user_name))
    if not users:
        return None

    assert len(users) < 2
    return users[0]

def no_such_user(user_name):
    return {"status":400, "message":"no such user %s" % user_name}

def is_friends(user1, user2):
    return True #FORNOW
    friends = list(db.session.query(Friend).filter(Friend.user_id == user1.id)\
                                 .filter(Friend.user_id == user2.id))
    if not friends:
        return False

    return True



api.add_resource(Listens, '/<string:user_name>/listens')
api.add_resource(Friends, '/<string:user_name>/friends')
api.add_resource(UserAPI, '/<string:user_name>')
api.add_resource(Queue, '/<string:user_name>/queue')
api.add_resource(Search, '/search/<string:search_text>')


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)

