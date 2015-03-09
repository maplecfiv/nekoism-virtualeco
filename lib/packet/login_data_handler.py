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

class LoginDataHandler:
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
				general.log("[login]",
					data[:2].encode("hex"), data[2:].encode("hex"))
			handler = self.name_map.get(data_type)
			if not handler:
				general.log_error("[login] unknow packet type",
					data[:2].encode("hex"), data[2:].encode("hex"))
				return
			try:
				handler(self, data_io)
			except:
				general.log_error("[login] handle_data error:", data.encode("hex"))
				general.log_error(traceback.format_exc())
	
	def do_0001(self, data_io):
		#接続・接続確認
		data = data_io.read()
		self.send("ffff")
		general.log("[login] eco version", unpack_unsigned_int(data[:4]))
		self.send("0002", data) #認証接続確認(s0001)の応答
		self.send("001e", self.word_front+self.word_back) #PASS鍵
		general.log("[login] send word",
			self.word_front.encode("hex"), self.word_back.encode("hex"),
		)
	
	def do_001f(self, data_io):
		#認証情報
		username = io_unpack_str(data_io)
		password_sha1 = io_unpack_raw(data_io)[:40]
		general.log("[login]", "login", username, password_sha1)
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
				if user.login_client:
					user.reset_login()
					self.send("0020", user, "isonline") #アカウント認証結果
					return
				user.reset_login()
				user.login_client = self
				self.user = user
				self.send("0020", user, "loginsucess") #アカウント認証結果
				self.send("0028", user) #4キャラクターの基本属性
				self.send("0029", user) #4キャラクターの装備
				break
		else:
			self.send("0020", user, "loginfaild") #アカウント認証結果
	
	def do_000a(self, data_io):
		#接続確認
		self.send("000b", data_io.read()) #接続・接続確認(s000a)の応答
	
	def do_00a0(self, data_io):
		#キャラクター作成
		#02 03313100 00 00 0000 32 0000
		num = io_unpack_byte(data_io)
		name = io_unpack_str(data_io)
		race = io_unpack_byte(data_io)
		gender = io_unpack_byte(data_io)
		hair = io_unpack_short(data_io)
		hair_color = io_unpack_byte(data_io)
		face = io_unpack_short(data_io)
		general.log("[login] create character:", "num", num, "name", name,
			"race", race, "gender", gender, "hair", hair,
			"haircolor", hair_color, "face", face)
		try:
			if self.user.pc_list[num]:
				self.send("00a1", "slotexist") #キャラクター作成結果
				return
			if users.get_pc_from_name(name):
				self.send("00a1", "nameexist") #キャラクター作成結果
				return
			if hair > 15 or hair_color < 50:
				raise ValueError(
					"user %s hair %s hair_color %s"%(
					self.user.name, hair, hair_color))
				return
			if not users.make_new_pc(
				self.user, num, name, race, gender, hair, hair_color, face):
				self.send("00a1", "slotexist") #キャラクター作成結果
				return
		except ValueError:
			self.send("00a1", "other") #キャラクター作成結果
			return
		else:
			self.send("00a1", "sucess") #キャラクター作成結果
			self.send("0028", self.user) #4キャラクターの基本属性
			self.send("0029", self.user) #4キャラクターの装備
	
	def do_00a5(self, data_io):
		#キャラクター削除 #num + delpassword
		num = io_unpack_byte(data_io)
		delpassword_md5 = io_unpack_raw(data_io)[:32]
		general.log("[login] remove character", "num", num,
			"delpassword", delpassword_md5)
		try:
			if self.user.delpassword != delpassword_md5:
				raise (ValueError, "delpassword error")
			with self.user.lock:
				p = self.user.pc_list[num]
				with users.user_list_lock:
					general.log("[login] remove pc id", p.id)
					users.pc_id_set.remove(p.id)
				os.remove(p.path, base=env.USER_DIR)
				self.user.pc_list[num] = None
			self.send("00a6", True) #キャラクター削除結果
		except ValueError:
			self.send("00a6", False) #キャラクター削除結果
		self.send("0028", self.user) #4キャラクターの基本属性
		self.send("0029", self.user) #4キャラクターの装備
	
	def do_00a7(self, data_io):
		#キャラクター選択
		num = io_unpack_byte(data_io)
		general.log("[login] select character", num)
		with self.user.lock:
			self.pc = self.user.pc_list[num]
		self.send("00a8", self.pc) #キャラクターマップ通知
	
	def do_0032(self, data_io):
		#接続先通知要求
		map_id = io_unpack_int(data_io)
		self.send("0033", "", "", "") #接続先通知要求(ログインサーバ/0032)の応答
	
	def do_002a(self, data_io):
		self.send("002b")
		#キャラ番号通知
		general.log("[login]", "request friend list")
		if self.pc:
			self.send("00dd", self.pc) #フレンドリスト(自キャラ)
			self.send("00de")
	
	def do_00c9(self, data_io):
		#whisper send
		name = io_unpack_str(data_io)
		message = io_unpack_str(data_io)
		p = users.get_pc_from_name(name)
		if p and p.online:
			#whisper message
			p.user.login_client.send("00ce", self.pc, message)
		else:
			self.send("00ca", name, -1) #whisper failed

LoginDataHandler.name_map = general.get_name_map(LoginDataHandler.__dict__, "do_")