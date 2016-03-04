# encoding: utf-8
"""
manager.py

Created by David Farrar  on 2011-11-30.
Copyright (c) 2011-2013  Exa Networks. All rights reserved.
"""

from exaproxy.util.log.logger import Logger
from exaproxy.util.active import ActiveCache

from .http import HTTPClient
from .icap import ICAPClient
from .tls import TLSClient

class ClientManager (object):
	def __init__(self, poller, configuration):
		self.total_sent4 = 0L
		self.total_sent6 = 0L
		self.total_requested = 0L
		self.bysock = ActiveCache()
		self.byname = {}
		self.buffered = []
		self._nextid = 0
		self.poller = poller
		self.log = Logger('client', configuration.log.client)
		self.http_max_buffer = configuration.http.header_size
		self.icap_max_buffer = configuration.icap.header_size
		self.tls_max_buffer = configuration.tls.header_size
		self.proxied = {
			'proxy' : configuration.http.proxied,
			'icap'  : configuration.icap.proxied,
			'tls'   : configuration.tls.proxied,
		}

	def __contains__(self, item):
		return item in self.bysock

	def lookupSocket (self, item):
		return self.byname.get(item, None)

	def getnextid (self):
		self._nextid += 1
		return str(self._nextid)

	def expire (self):
		expiring = self.bysock.shift(1)

		for sock, (client, source) in expiring.iteritems():
			self.cleanup(client)

		return len(expiring)

	def httpConnection (self, sock, peer, source):
		name = self.getnextid()
		client = HTTPClient(name, sock, peer, self.log, self.http_max_buffer, self.proxied.get(source))

		self.bysock[sock] = client, source
		self.byname[name] = sock

		# watch for the opening request
		self.poller.addReadSocket('read_client', client.sock)

		#self.log.info('new id %s (socket %s) in clients : %s' % (name, sock, sock in self.bysock))
		return peer

	def icapConnection (self, sock, peer, source):
		name = self.getnextid()
		client = ICAPClient(name, sock, peer, self.log, self.icap_max_buffer, self.proxied.get(source))

		self.bysock[sock] = client, source
		self.byname[name] = sock

		# watch for the opening request
		self.poller.addReadSocket('read_client', client.sock)

		#self.log.info('new id %s (socket %s) in clients : %s' % (name, sock, sock in self.bysock))
		return peer

	def tlsConnection (self, sock, peer, source):
		name = self.getnextid()
		client = TLSClient(name, sock, peer, self.log, self.tls_max_buffer, self.proxied.get(source))

		self.bysock[sock] = client, source
		self.byname[name] = sock

		# watch for the opening request
		self.poller.addReadSocket('read_client', client.sock)

		#self.log.info('new id %s (socket %s) in clients : %s' % (name, sock, sock in self.bysock))
		return peer

	def readData (self, sock):
		client, source = self.bysock.get(sock, (None, None))
		if client:
			name, peer, request, subrequest, content = client.readData()
			if request:
				self.total_requested += 1
				# Parsing of the new request will be handled asynchronously. Ensure that
				# we do not read anything from the client until a request has been sent
				# to the remote webserver.
				# Since we just read a request, we know that the cork is not currently
				# set and so there's no risk of it being erroneously removed.
				self.poller.corkReadSocket('read_client', sock)

			elif request is None:
				self.cleanup(client)
		else:
			self.log.error('trying to read from a client that does not exist %s' % sock)
			name, peer, request, subrequest, content = None, None, None, None, None


		return name, peer, request, subrequest, content, source

	def sendData (self, sock, data):
		client, source = self.bysock.get(sock, (None, None))
		if client:
			name = client.name
			res = client.writeData(data)

			if res is None:
				# close the client connection
				self.cleanup(client)

				buffered, had_buffer, sent4, sent6 = None, None, 0, 0
				result = None
				buffer_change = None
			else:
				buffered, had_buffer, sent4, sent6 = res
				self.total_sent4 += sent4
				self.total_sent6 += sent6
				result = buffered

			if buffered is True and had_buffer is False:
				assert sock not in self.buffered

			elif buffered is False and had_buffer is True:
				assert sock in self.buffered

			if buffered:
				if sock not in self.buffered:
					self.buffered.append(sock)
					buffer_change = True

					# watch for the socket's send buffer becoming less than full
					self.poller.addWriteSocket('write_client', client.sock)
				else:
					buffer_change = False

			elif had_buffer and sock in self.buffered:
				self.buffered.remove(sock)
				buffer_change = True

				# we no longer care about writing to the client
				self.poller.removeWriteSocket('write_client', client.sock)

			else:
				buffer_change = False
		else:
			result = None
			buffer_change = None
			name = None

		return result, buffer_change, name, source


	def parseRemaining (self, remaining):
		nb_to_read = 0

		if isinstance(remaining, basestring):
			mode = 'chunked' if remaining == 'chunked' else 'passthrough'

		elif remaining > 0:
			mode = 'transfer'
			nb_to_read = remaining

		elif remaining == 0:
			mode = ''

		else:
			mode = 'passthrough'

		return mode, nb_to_read

	def startData (self, sock, data, remaining):
		client, source = self.bysock.get(sock, (None, None))

		try:
			mode, nb_to_read = self.parseRemaining(remaining)
			command, d = data if client is not None else (None, None)

		except (ValueError, TypeError), e:
			self.log.error('invalid command sent to client %s' % client.name)
			command, d = None, None

		if not client or command is None:
			return None, source

		name, peer, res = client.startData(command, d)

		if res is not None:
			name, peer, request, subrequest, content = client.readRelated(mode, nb_to_read)

			buffered, had_buffer, sent4, sent6 = res

			self.poller.uncorkReadSocket('read_client', client.sock)

			self.total_sent4 += sent4
			self.total_sent6 += sent6

		else:
			self.cleanup(client)
			return None, source


		if request:
			self.total_requested += 1
			self.log.info('reading multiple requests')
			self.cleanup(client)
			buffered, had_buffer = None, None
			content = None

		elif request is None:
			self.cleanup(client)
			buffered, had_buffer = None, None
			content = None

		if buffered is True and had_buffer is False:
			self.buffered.append(client.sock)

			self.poller.addWriteSocket('write_client', client.sock)

		elif buffered is False and had_buffer is True:
			self.buffered.remove(client.sock)

			self.poller.removeWriteSocket('write_client', client.sock)

		return content, source


	def corkUpload (self, sock):
		if sock in self.bysock:
			self.poller.corkReadSocket('read_client', sock)

	def uncorkUpload (self, sock):
		if sock in self.bysock:
			self.poller.uncorkReadSocket('read_client', sock)

	def cleanup (self, client):
		if client:
			self.log.debug('cleanup for socket %s' % client.sock)
			self.bysock.pop(client.sock, None)
			self.byname.pop(client.name, None)

			self.poller.removeWriteSocket('write_client', client.sock)
			self.poller.removeReadSocket('read_client', client.sock)

			client.shutdown()
		else:
			self.log.error('COULD NOT CLEAN UP SOCKET %s' % client.sock)

		if client.sock in self.buffered:
			self.buffered.remove(client.sock)

	def softstop (self):
		if len(self.byname) > 0:
			return False

		self.log.critical('no more client connection, exiting.')
		return True

	def stop (self):
		for client, source in self.bysock.itervalues():
			client.shutdown()

		self.poller.clearRead('read_client')
		self.poller.clearWrite('write_client')

		self.bysock = {}
		self.byname = {}
		self.buffered = []
