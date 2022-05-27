import json
import time
import unittest
from multiprocessing import Process
from urllib.parse import urlparse, parse_qs

import requests
from flask import Flask
from flask_ask_sdk.skill_adapter import SkillAdapter

from jellyfin_alexa_skill.alexa.handler import get_skill_builder
from jellyfin_alexa_skill.alexa.web.skill import get_skill_blueprint
from jellyfin_alexa_skill.config import SUPPORTED_LANGUAGES
from jellyfin_alexa_skill.database.db import get_playback, connect_db, clear_db
from jellyfin_alexa_skill.database.model.playback import QueueItem
from jellyfin_alexa_skill.database.model.user import User
from jellyfin_alexa_skill.jellyfin.api.client import JellyfinClient, MediaType
from jellyfin_alexa_skill.l10n import get_translation
from jellyfin_alexa_skill.main import GunicornApplication

ALEXA_USER_ID = "amzn1.ask.account.42424242"
ALEXA_AUTH_TOKEN = "nicetoken4242"

REQUEST_TEMPLATE = {
    "version": "1.0",
    "session": {
        "new": "true",
        "sessionId": "amzn1.echo-api.session.00000000-1111-2222-3333-444444444444",
        "application": {
            "applicationId": "amzn1.ask.skill.11111111-2222-3333-4444-555555555555"
        },
        "attributes": {},
        "user": {
            "userId": ALEXA_USER_ID,
            "accessToken": ALEXA_AUTH_TOKEN
        }
    },
    "context": {
        "Viewports": [
            {
                "type": "APL",
                "id": "main",
                "shape": "RECTANGLE",
                "dpi": 213,
                "presentationType": "STANDARD",
                "canRotate": "false",
                "configuration": {
                    "current": {
                        "mode": "HUB",
                        "video": {
                            "codecs": [
                                "H_264_42",
                                "H_264_41"
                            ]
                        },
                        "size": {
                            "type": "DISCRETE",
                            "pixelWidth": 1280,
                            "pixelHeight": 800
                        }
                    }
                }
            }
        ],
        "AudioPlayer": {
            "playerActivity": "IDLE"
        },
        "Viewport": {
            "experiences": [
                {
                    "arcMinuteWidth": 346,
                    "arcMinuteHeight": 216,
                    "canRotate": "false",
                    "canResize": "false"
                }
            ],
            "mode": "HUB",
            "shape": "RECTANGLE",
            "pixelWidth": 1280,
            "pixelHeight": 800,
            "dpi": 213,
            "currentPixelWidth": 1280,
            "currentPixelHeight": 800,
            "touch": [
                "SINGLE"
            ],
            "video": {
                "codecs": [
                    "H_264_42",
                    "H_264_41"
                ]
            }
        },
        "Extensions": {
            "available": {
                "aplext:backstack:10": {}
            }
        },
        "System": {
            "application": {
                "applicationId": "amzn1.ask.skill.11111111-2222-3333-4444-555555555555"
            },
            "user": {
                "userId": ALEXA_USER_ID,
                "accessToken": ALEXA_AUTH_TOKEN
            },
            "device": {
                "deviceId": "amzn1.ask.device.1234567890",
                "supportedInterfaces": {
                    "AudioPlayer": {}
                }
            },
            "apiEndpoint": "https://api.eu.amazonalexa.com",
            "apiAccessToken": "apitoken.4242"
        }
    }
}

JELLYFIN_USER_ID = "a8e5cac72a3a4ad8a3069f95b4a811ee"
JELLYFIN_TOKEN = "c98e5a373ff04faebc46daec14572eed"

DB_USER = "skill"
DB_PASSWORD = "pw"
DB_HOST = "127.0.0.1"
DB_PORT = 5432

SKILL_WEB_APP_HOST = "127.0.0.1"
SKILL_WEB_APP_PORT = 1456

jellyfin_endpoint = "http://localhost:8096"


class TestSkillResponseControl(unittest.TestCase):
    skill_process = None

    def post_request(self, data):
        response = requests.post(f"http://{SKILL_WEB_APP_HOST}:{SKILL_WEB_APP_PORT}", json=data)
        self.assertEqual(response.status_code, 200)

        return json.loads(response.text)

    @classmethod
    def setUpClass(cls) -> None:
        """
        Start the skill server and insert an authenticated test user. Wait for the server to start.
        """

        # check if the jellyfin server is up
        max_attempts = 5
        for i in range(max_attempts):
            try:
                requests.get(jellyfin_endpoint)
                print("Jellyfin server is up")
                break
            except requests.exceptions.ConnectionError:
                time.sleep(5)
                if i == max_attempts - 1:
                    raise Exception("Jellyfin server is not up")

        def skill_app():
            app_name = "Jellyfin_Alexa_Skill"
            skill_id = "amzn1.ask.skill.11111111-2222-3333-4444-555555555555"

            app = Flask(__name__)

            # connect the skill process to the db
            connect_db(DB_USER,
                       DB_PASSWORD,
                       DB_HOST,
                       DB_PORT)

            jellyfin_client = JellyfinClient(server_endpoint=jellyfin_endpoint, client_name=app_name)

            skill_adapter = SkillAdapter(skill=get_skill_builder(jellyfin_client).create(),
                                         skill_id=skill_id,
                                         app=app)

            # disable verification of the request because we use the localhost as sender
            skill_adapter._webservice_handler._verifiers = []

            # register skill routes
            skill_blueprint = get_skill_blueprint(skill_adapter)
            app.register_blueprint(skill_blueprint)

            options = {
                "bind": f"{SKILL_WEB_APP_HOST}:{SKILL_WEB_APP_PORT}",
                "workers": 1,
            }
            GunicornApplication(app, options).run()

        # connect this process to the db too
        connect_db(DB_USER,
                   DB_PASSWORD,
                   DB_HOST,
                   DB_PORT)

        cls.skill_process = Process(target=skill_app)
        cls.skill_process.start()

        print("Start skill app on port {}".format(SKILL_WEB_APP_PORT))

        # wait for the skill to start on hosts port
        max_attempts = 5
        for i in range(max_attempts):
            try:
                requests.get(f"http://{SKILL_WEB_APP_HOST}:{SKILL_WEB_APP_PORT}")
                print("Skill app successfully started")
                break
            except requests.exceptions.ConnectionError:
                time.sleep(5)
                if i == max_attempts - 1:
                    raise Exception("Skill web app is not up")

    @classmethod
    def tearDownClass(cls) -> None:
        """
        Stop the skill server process.
        """
        cls.skill_process.terminate()
        cls.skill_process.join()

        clear_db()

    @classmethod
    def setUp(cls) -> None:
        clear_db()

        # insert dummy authenticated test user
        User.create(alexa_auth_token=ALEXA_AUTH_TOKEN,
                    jellyfin_user_id=JELLYFIN_USER_ID,
                    jellyfin_token=JELLYFIN_TOKEN)

    def test_no_audio_interface(self):
        """
        Test the skill response with no audio interface.
        The skill should notify the user that the device is not supported.
        """

        requests_data = REQUEST_TEMPLATE.copy()

        requests_data["request"] = {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.99999999-8888-7777-6666-555555555555",
            "locale": "en-US",
            "timestamp": "2022-01-01T12:42:42Z",
            "shouldLinkResultBeReturned": "false"
        }

        requests_data["context"]["System"]["device"]["supportedInterfaces"] = {}
        del requests_data["context"]["AudioPlayer"]

        res = self.post_request(requests_data)
        self.assertEqual(res["response"]["outputSpeech"]["ssml"],
                         "<speak>Sorry, this device does not support media playback.</speak>")

    def test_not_authenticated(self):
        """
        Check if the skill redirects to the account linking page when the user is not authenticated.
        """

        requests_data = REQUEST_TEMPLATE.copy()

        # use a not authenticated user
        requests_data["session"]["user"]["accessToken"] = "invalid"
        requests_data["context"]["System"]["user"]["accessToken"] = "invalid"

        with self.subTest("LaunchRequest"):
            requests_data["request"] = {
                "type": "LaunchRequest",
                "requestId": "amzn1.echo-api.request.99999999-8888-7777-6666-555555555555",
                "locale": "en-US",
                "timestamp": "2022-01-01T12:42:42Z",
                "shouldLinkResultBeReturned": "false"
            }

            res = self.post_request(requests_data)
            self.assertEqual(res["response"]["card"]["type"], "LinkAccount")

        with self.subTest("PlayFavoritesIntent"):
            requests_data["request"] = {
                "type": "IntentRequest",
                "requestId": "amzn1.echo-api.request.99999999-8888-7777-6666-555555555555",
                "locale": "en-US",
                "timestamp": "2022-01-01T12:42:42Z",
                "intent": {
                    "name": "PlayFavoritesIntent",
                    "confirmationStatus": "NONE",
                    "slots": {
                        "media_type": {
                            "name": "media_type",
                            "confirmationStatus": "NONE"
                        }
                    }
                }
            }

            res = self.post_request(requests_data)
            self.assertEqual(res["response"]["card"]["type"], "LinkAccount")

    def test_launch_multilang(self):
        requests_data = REQUEST_TEMPLATE.copy()

        requests_data["request"] = {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.99999999-8888-7777-6666-555555555555",
            "timestamp": "2022-01-01T12:42:42Z",
            "shouldLinkResultBeReturned": "false"
        }

        for locale in SUPPORTED_LANGUAGES:
            with self.subTest(f"LaunchRequest {locale}"):
                requests_data["request"]["locale"] = locale
                res = self.post_request(requests_data)
                translation = get_translation(requests_data["request"]["locale"])
                self.assertEqual(res["response"]["outputSpeech"]["ssml"],
                                 f"<speak>{translation.gettext('Welcome to Jellyfin Player skill, what can I play?')}</speak>")

    def test_launch_request_intent_resume_playback(self):
        requests_data = REQUEST_TEMPLATE.copy()

        requests_data["request"] = {
            "type": "LaunchRequest",
            "requestId": "amzn1.echo-api.request.99999999-8888-7777-6666-555555555555",
            "timestamp": "2022-01-01T12:42:42Z",
            "shouldLinkResultBeReturned": "false"
        }

        # insert a dummy playback for the user
        media_id = "ccf19d58cf1a38fa18ea0e2dd0da0e5b"

        playback = get_playback(ALEXA_USER_ID)

        dummy_queue_item = QueueItem.create(id=0, item_id=media_id, idx=0, media_type=MediaType.AUDIO)
        playback.set_queue([dummy_queue_item])

        requests_data["request"]["locale"] = "en-US"
        res = self.post_request(requests_data)

        self.assertIn("directives", res["response"])
        self.assertTrue(len(res["response"]["directives"]) == 1)
        self.assertIn("AudioPlayer.Play", res["response"]["directives"][0]["type"])

        parsed_url = urlparse(res["response"]["directives"][0]["audioItem"]["stream"]["url"])
        self.assertEqual(parsed_url.path, "/Audio/{}/universal".format(media_id))
        self.assertEqual(parse_qs(parsed_url.query)["api_key"][0], JELLYFIN_TOKEN)


if __name__ == "__main__":
    unittest.main()
