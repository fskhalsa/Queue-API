import datetime
import json

from flask import Flask, request
from flask.ext.restful import Resource, Api, reqparse
import requests

import models
from models import Song, User, Artist, Album
from models import db_session

API_URL = "http://ws.audioscrobbler.com/2.0/?"
API_KEY = "7caf7bfb662c58f659df4446c7200f3c&"

app = Flask(__name__)
api = Api(app)

parser = reqparse.RequestParser()
parser.add_argument('song', type=dict)
parser.add_argument('auth', type=str)
parser.add_argument('from_user_id', type=str)
parser.add_argument('default', type=str)

def fix_lastfm_data(data):
    data['recenttracks'][u'metadata'] = data['recenttracks'].pop('@attr')
    data['recenttracks'][u'tracks'] = data['recenttracks'].pop('track')

    for i, track in enumerate(data['recenttracks']['tracks']):

        track['album'][u'name'] = track['album'].pop('#text')
        track['streamable'] = bool(int(track['streamable']))
        track['loved'] = bool(int(track['loved']))

        del track['artist']['url']

        if track.has_key("date"):
            del track['date']['#text']
            track.update(track["date"])
            del track['date']

        if track.has_key("@attr"):
            track['nowplaying'] = True
            del track["@attr"]

        track[u'images'] = track.pop('image')

        for image in track['images']:
            image[u'url'] = image.pop('#text')

        track['artist'][u'images'] = track['artist'].pop('image')

        for image in track['artist']['images']:
            image[u'url'] = image.pop('#text')

    return data






def get_args(args):
    pass

class Listens(Resource):
    def get(self, user_name):
        data = requests.get("%smethod=user.getrecenttracks&user=%s&api_key=%sformat=json&extended=1" % (API_URL, user_name, API_KEY)).json()
        return fix_lastfm_data(data)


class Friends(Resource):
    def get(self, user_name):
        args = parser.parse_args()
        auth = map(args.get, ['auth'])
        pass

class UserAPI(Resource):
    def post(self, user_name):
        args = request.json
        auth, default = map(args.get, ['auth', 'default'])
        u = User(user_name, auth)
        db_session.add(u)
        db_session.commit()

        return {"status":"OK"}


class Queue(Resource):
    def get(self, user_name):
        user_id = db_session.query(User.id).filter(User.uname == user_name).one()[0]
        orm_songs = db_session.query(Song).filter(Song.user_id == user_id).all()

        for song in db_session.query(Song):
            print song
        songs = []

        for orm_song in db_session.query(Song):
            songs.append(orm_song.dictify())

        return {"queue":songs}

    def post(self, user_name):

        args = request.json
        auth, song, from_user_id = map(args.get, ['auth', 'song', 'from_user_id'])
        from_user = db_session.query(User).filter(User.uname == from_user_id).one()
        to_user = db_session.query(User).filter(User.uname == user_name).one()

        if from_user and to_user:

            artist = song['artist']
            orm_artist = Artist(name=artist['name'], mbid=artist['mbid'],
                                small_image_link=artist['image']['small'],
                                medium_image_link=artist['image']['small'],
                                large_image_link=artist['image']['small'])

            album = song['album']
            orm_album = Album(name=album['name'], mbid=album['mbid'])

            orm_song = Song(user=to_user,queued_by_user=from_user,
                            listened=False, name=song['name'],
                            date_queued=datetime.datetime.utcnow(),
                            small_image_link=song['image']['small'],
                                medium_image_link=song['image']['small'],
                                large_image_link=song['image']['small'])

            orm_song.artist = orm_artist
            orm_song.album = orm_album
            db_session.add(orm_song)
            db_session.add(orm_album)
            db_session.add(orm_artist)

            db_session.commit()

            return {"status":"OK"}
        return {"status":"Not OK"}





api.add_resource(Listens, '/<string:user_name>/listens')
api.add_resource(Friends, '/<string:user_name>/friends')
api.add_resource(UserAPI, '/<string:user_name>')
api.add_resource(Queue, '/<string:user_name>/queue')


@app.teardown_request
def shutdown_session(exception=None):
    db_session.remove()


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)
