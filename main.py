#!/usr/bin/env python
"""
Python API Backend
"""

from typing import Optional

import logging
import uuid
import json

import tornado.web
import tornado.httpserver
import tornado.ioloop
import tornado.websocket
import tornado.options

from model_memo import ModelMemo
from data_processor import DataProcessor
from model_selection import ModelSelection
from models.model import Prediction

PORT=8889

class HttpApiHandler(tornado.web.RequestHandler): # pylint: disable=W0223
    """
    Tornado HTTP API Handler
    """
    @classmethod
    def url(cls, args: Optional[dict] = None, address = r'/'):
        """
        Define URL for this HTTP API
        """
        args = {} if args is None else args
        return (address, cls, args)

    def _set_model_selection(self, model_selection: Optional[ModelSelection]):
        if not isinstance(model_selection, ModelSelection):
            return
        self.model_selection = model_selection # pylint: disable=W0201

    def initialize(self, model_selection: Optional[ModelSelection] = None):
        """
        Init HTTP API
        """
        self._set_model_selection(model_selection)

    def set_default_headers(self):
        self.set_header('Access-Control-Allow-Origin', '*')
        self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.set_header('Access-Control-Allow-Headers', 'x-requested-with')

    def options(self):
        """
        Define No Body for HTTP OPTIONS
        """
        self.set_status(204)
        self.finish()

    def get(self):
        """
        Define Return for HTTP GET /
        """
        self.write({key: value['canonical'] for key, value in self.model_selection.get_models().items()})

class WsChannelHandler(tornado.websocket.WebSocketHandler): # pylint: disable=W0223
    """
    Tornado WebSocket API Handler
    """
    @classmethod
    def url(cls, args: Optional[dict] = None, address = r'/ws'):
        """
        Define URL for this Websocket API
        """
        args = {} if args is None else args
        return (address, cls, args)

    def _set_channel(self, channel: Optional[str]):
        self.channel = channel # pylint: disable=W0201

    def _set_memo(self, memo: Optional[ModelMemo]):
        if not isinstance(memo, ModelMemo):
            return
        self.memo = memo # pylint: disable=W0201

    def _set_model_selection(self, model_selection: Optional[ModelSelection]):
        if not isinstance(model_selection, ModelSelection):
            return
        self.model_selection = model_selection # pylint: disable=W0201

    def _load_architecture(self, name: str):
        """
        Load Architecture to Model
        """
        if not isinstance(self.memo, ModelMemo):
            logging.warning('API runs without memoisation!')
            return self.model_selection.get_model(name)()
        if not self.memo.has_memo(name):
            self.memo.add_memo(name, self.model_selection.get_model(name)())
        return self.memo.get_memo(name)

    def _get_prediction_objects(self, data_processor):
        prediction_a = prediction_b = self._load_architecture(data_processor.architecture_a).trigger_predict(data_processor.face_detection['face_image'])
        if not data_processor.is_normal_mode():
            prediction_b = self._load_architecture(data_processor.architecture_b).trigger_predict(data_processor.face_detection['face_image'])
        return prediction_a, prediction_b

    def initialize(self, memo = None, model_selection = None):
        """
        Tornado WS Init
        """
        self._set_channel(None)
        self._set_memo(memo)
        self._set_model_selection(model_selection)

    def set_default_headers(self):
        self.set_header('Access-Control-Allow-Origin', '*')
        # self.set_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.set_header('Access-Control-Allow-Headers', 'x-requested-with')

    def open(self, channel=None): # pylint: disable=W0221
        """
        Tornado WS Open Connection Handler
        """
        if channel is None:
            self._set_channel(str(uuid.uuid4()))

    def on_message(self, message):
        """
        Tornado WS Message Handler
        """
        def run_process():
            data_processor = DataProcessor(self.model_selection).postprocess_message(message).face_detect()
            if not data_processor.validation_result or data_processor.face_detection['face_image'] is None:
                logging.debug('Returns Error with data: %s %s', data_processor.face_detection, data_processor.validation_result)
                self.write_message(json.dumps({
                    "status": "error"
                }))
                return
            prediction_a, prediction_b = self._get_prediction_objects(data_processor)

            self.write_message(json.dumps({
                'data': {
                    'architecture_a': {
                        'name': data_processor.architecture_a,
                        'canonical_name': self.model_selection.get_model_canonical_name(data_processor.architecture_a),
                        'detection': 'drowsy' if prediction_a['prediction'] == Prediction.DROWSY else 'alert',
                        'confidence': prediction_a['confidence']
                    },
                    'architecture_b': {
                        'name': data_processor.architecture_b,
                        'canonical_name': self.model_selection.get_model_canonical_name(data_processor.architecture_b),
                        'detection': 'drowsy' if prediction_b['prediction'] == Prediction.DROWSY else 'alert',
                        'confidence': prediction_b['confidence']
                    },
                    'position': data_processor.get_face_detection()['position'],
                },
                'status': 'success'
            }))
            return
        run_process()
        # Signal end of message queue from request
        self.write_message({
            'status': 'done',
            'message': 'Hooray... Session done!'
        })

    def on_close(self):
        pass

    def check_origin(self, origin):
        return True

def make_app(memo: ModelMemo, model_selection: ModelSelection):
    """
    Create Tornado App
    """
    return tornado.web.Application([
        HttpApiHandler.url({
            'model_selection': model_selection
        }),
        WsChannelHandler.url({
            'memo': memo,
            'model_selection': model_selection
        })
    ])

def load_memo(model_selection: ModelSelection):
    """
    Startup Memo Loader
    """
    memo = ModelMemo()
    for model_name in model_selection.get_model_keys():
        memo.add_memo(model_name, model_selection.get_model(model_name)())
    return memo

if __name__ == "__main__":
    logging.basicConfig(format='[%(levelname)s] %(message)s', level=logging.INFO)
    g_model_selection = ModelSelection()
    app = make_app(load_memo(g_model_selection), g_model_selection)
    http_server = tornado.httpserver.HTTPServer(app)
    http_server.listen(PORT)
    logging.info('Listening on port %s', PORT)
    tornado.ioloop.IOLoop.instance().start()