import os
import asyncio
import logging
import json
import signal
import functools
import ipaddress
from concurrent.futures import CancelledError

from aiohttp import client
from aiotg import Bot


with open('config.json') as cfg:
    CONFIG = json.load(cfg)

API_TOKEN = os.environ.get('IPINFOIO_TELEGRAM_API_TOKEN', None)
if API_TOKEN:
    CONFIG['api_token'] = API_TOKEN

BOTAN_TOKEN = os.environ.get('BOTAN_TOKEN', None)
if BOTAN_TOKEN:
    CONFIG['botan_token'] = BOTAN_TOKEN

DEBUG = CONFIG.pop('debug', False)

logger = logging.getLogger(__name__)

IPINFO = 'https://ipinfo.io/'
GREETING = ('Hi! I\'m ipinfo.io bot and I can give you IP geolocation '
            'info about any IP address you send to me.\n\n'
            'You can control me by sending these commands:\n\n'
            '/ip {ip} - get infromation about the IP\n'
            '/geo {ip} - get location on a map for the IP')

HELP = ('This bot allows you to get a simple information about '
        'giving IP address. All data provided by http://ipinfo.io/ service.')

BASE_TEMPLATE = '''
*{ip}*

*Hostname*: {hostname}
*Network*: {org}
*Country*: {country}
*City*: {city}
*Latitude/Longitude*: {loc}
'''
REQUIRED_KEYS = ['org', 'country', 'loc', 'city', 'hostname']


def check_ip(method_to_decorate):
    async def wrapper(self, chat, match, **kwargs):
        ip = match.group(2)
        logger.debug(match)
        if ip is None or ip == '':
            text = ('Please provide a valid ipv4 or ipv6 '
                    'address for this command. '
                    'Use /help command for examples.')
            msg = {'text': text, 'parse_mode': 'Markdown'}
            await chat._send_to_chat('sendMessage', **msg)
            return
        try:
            ip_address = ipaddress.ip_address(ip)
            return await method_to_decorate(self, chat, match, ip=ip_address)
        except ValueError:
            message = ('"{}" is not valid '
                       'ipv4 or ipv6 address'.format(ip))
            await chat.reply(message)
            return
    return wrapper


class IPInfoIOBot(Bot):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._commands = [
            (r'/start', self.greeting),
            (r'/help', self.help),
            (r'/ping', self.ping),
            (r'(/ip (.+)|/ip)', self.ip_base),
            (r'(/geo (.+)|/geo)', self.ip_geo)
        ]

    def shutdown():
        logger.info('received stop signal, cancelling tasks...')
        for task in asyncio.Task.all_tasks():
            logger.info(task)
            task.cancel()
        logger.info('bye, exiting in a minute...')

    def run(self):
        loop = asyncio.get_event_loop()
        loop.add_signal_handler(
            signal.SIGTERM, functools.partial(self.shutdown, loop))
        loop.add_signal_handler(
            signal.SIGHUP, functools.partial(self.shutdown, loop))
        try:
            while True:
                loop.run_until_complete(self.loop())
        except CancelledError:
            logger.info('CancelledError')
        except KeyboardInterrupt:
            logger.info('Shutting down bot...')
        loop.close()

    async def track_message(self, message, name):
        uid = message.get('result', {}).get('chat', {}).get('id', None)
        if self.botan_token:
            logger.debug(
                'Tracking message: "{}", from user: {}'.format(name, uid))
            if uid:
                self.track({'from': {'id': uid}}, name)
            else:
                logger.debug('Can not get user id')

    async def ping(self, chat, match):
        '''Send a "pong" reply on "/ping" command
        '''
        logger.info('Got /ping command, sending pong reply')
        await chat.send_text('test pong!')

    async def ipinfo_query(self, params):
        url = '{}{}'.format(IPINFO, params)
        logger.debug('Requesting: {}'.format(url))
        response = await client.get(url)
        return await response.json()

    async def greeting(self, chat, match):
        logger.debug('Got /start command, sending greeting message')
        message = {'text': HELP, 'parse_mode': 'Markdown'}
        await chat._send_to_chat('sendMessage', **message)

    async def help(self, chat, match):
        logger.debug('Got /help command, sending help text')
        message = {'text': GREETING, 'parse_mode': 'Markdown'}
        response = await chat._send_to_chat('sendMessage', **message)
        await self.track_message(response, 'Help')

    @check_ip
    async def ip_base(self, chat, match, **kwargs):
        logger.debug('Got /ip command, validating ip address')
        ip_address = kwargs.get('ip')
        data = await self.ipinfo_query('{}/json'.format(ip_address))
        for v in REQUIRED_KEYS:
            if v not in data.keys():
                data[v] = ''
        reply = BASE_TEMPLATE.format(**data)
        message = {'text': reply, 'parse_mode': 'Markdown'}
        response = await chat._send_to_chat('sendMessage', **message)
        await self.track_message(response, 'Ip')

    @check_ip
    async def ip_geo(self, chat, match, **kwargs):
        logger.debug('Got /geo command, validating ip address')
        ip_address = kwargs.get('ip')
        message = await self.ipinfo_query('{}/geo'.format(ip_address))
        if 'loc' in message.keys():
            message = {
                'latitude': message['loc'].split(',')[0],
                'longitude': message['loc'].split(',')[1]
            }
            method = 'sendLocation'
        else:
            message = {
                'text': 'Sorry, location is unknown for this address'
            }
            method = 'sendMessage'
        response = await chat._send_to_chat(method, **message)
        await self.track_message(response, 'Ip_Geo')


if __name__ == '__main__':
    bot = IPInfoIOBot(**CONFIG)
    if DEBUG:
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s %(levelname)s %(message)s')
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s %(message)s')
    logger.info('Starting bot...')
    bot.run()
