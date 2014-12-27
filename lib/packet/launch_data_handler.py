#!/usr/bin/env python
# -*- coding: utf-8 -*-
import traceback
import hashlib
import os
from lib import env
from lib import general
from lib.packet import packet
from lib import users
from lib.packet.packet_struct import *
DATA_TYPE_NOT_PRINT = (
	"000a", #接続確認
)

class LaunchDataHandler:
	def __init__(self):
		self.user = None
		self.pc = None
		self.word_front = pack_unsigned_int(
			general.randint(0, general.RANGE_INT[1])
		)
		self.word_back = pack_unsigned_int(
			general.randint(0, general.RANGE_INT[1])
		)
	
	def send(self, *args):
		self.send_packet(general.encode(packet.make(*args), self.rijndael_obj))
	
	def stop(self):
		if self.user:
			self.user.reset_login()
			self.user = None
		self._stop()
	
	def handle_data(self, data_decode):
		#000a 0001 000003f91e07e221
		data_decode_io = general.stringio(data_decode)
		while True:
			data = io_unpack_short_raw(data_decode_io)
			if not data:
				break
			data_io = general.stringio(data)
			data_type = data_io.read(2).encode("hex")
			if data_type not in DATA_TYPE_NOT_PRINT:
				general.log("[launch]",
					data[:2].encode("hex"), data[2:].encode("hex"))
			handler = self.name_map.get(data_type)
			if not handler:
				general.log_error("[launch] unknow packet type",
					data[:2].encode("hex"), data[2:].encode("hex"))
				return
			try:
				handler(self, data_io)
			except:
				general.log_error("[launch] handle_data error:", data.encode("hex"))
				general.log_error(traceback.format_exc())
	
	def do_0001(self, data_io):
		#接続・接続確認
		data = data_io.read()
		general.log("[launch] eco version", unpack_unsigned_int(data[:4]))
		self.send("0002", data) #認証接続確認(s0001)の応答
		self.send("001e", self.word_front+self.word_back) #PASS鍵
		general.log("[launch] send word",
			self.word_front.encode("hex"), self.word_back.encode("hex"),
		)
	
	def do_000a(self, data_io):
		#接続確認
		self.send("000b", data_io.read()) #接続・接続確認(s000a)の応答
	
	def do_001f(self, data_io):
		#認証情報
		username = io_unpack_str(data_io)
		password_sha1 = io_unpack_raw(data_io)[:40]
		general.log("[launch]", "login", username, password_sha1)
		for user in users.get_user_list():
			with user.lock:
				if user.name != username:
					continue
				user_password_sha1 = hashlib.sha1(
					"".join((str(unpack_unsigned_int(self.word_front)),
							user.password,
							str(unpack_unsigned_int(self.word_back)),
							))).hexdigest()
				if user_password_sha1 != password_sha1:
					self.send("0020", user, "loginfaild") #アカウント認証結果
					return
				user.reset_launch()
				user.launch_client = self
				self.user = user
				self.send("0020", user, "loginsucess") #アカウント認証結果
				break
		else:
			self.send("0020", user, "loginfaild") #アカウント認証結果
	
	def do_0031(self, data_io):
		self.send("0032")
		self.send("0033", "launch", "local1", "127.0.0.1:13000")
		self.send("0033", "launch", "local2", "127.0.0.1:13000")
		self.send("0033", "launch", "local3", "127.0.0.1:13000")
		self.send("0034")
	
LaunchDataHandler.name_map = general.get_name_map(LaunchDataHandler.__dict__, "do_")