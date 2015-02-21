#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
import hashlib
import random
import contextlib
import traceback
import time
from lib import env
from lib import general
from lib.packet import packet
from lib import users
from lib import script
from lib import pets
from lib import monsters
from lib import db
from lib import skills
from lib import usermaps
from lib.packet.packet_struct import *
DATA_TYPE_NOT_PRINT = (
	"11f8", #自キャラの移動
	"0032", #接続確認(マップサーバとのみ) 20秒一回
	"0fa5", #戦闘状態変更通知
)
DATA_TYPE_CANCEL_TRADE_WHEN_EXCEPT = (
	"0a16", #トレードキャンセル
	"0a14", #トレードのOK状態
	"0a15", #トレードのTradeを押した際に送信
	"0a1b", #トレードウィンドウに置いたアイテム・金の情報を送信？
	"0a0a", #send trade ask
	"0a0d", #trade ask answer
)

class MapDataHandler:
	def __init__(self):
		self.user = None
		self.pc = None
		self.word_front = pack_unsigned_int(
			general.randint(0, general.RANGE_INT[1])
		)
		self.word_back = pack_unsigned_int(
			general.randint(0, general.RANGE_INT[1])
		)
		self.send_login_event = env.SEND_LOGIN_EVENT
	
	def send(self, *args):
		self.send_packet(general.encode(packet.make(*args), self.rijndael_obj))
	
	def send_map_without_self(self, *args):
		with self.pc.lock:
			if not self.pc.map_obj:
				return
			script.send_map_obj(self.pc.map_obj, (self.pc,), *args)
	
	def send_map(self, *args):
		with self.pc.lock:
			if not self.pc.map_obj:
				general.log_error("[ map ] send_map: not self.pc.map_obj", self.pc)
				return
			script.send_map_obj(self.pc.map_obj, (), *args)
	
	def send_server(self, *args):
		with self.pc.lock:
			script.send_server(*args)
	
	def stop(self):
		if self.user:
			self.user.reset_map()
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
				general.log("[ map ]",
					data[:2].encode("hex"), data[2:].encode("hex"))
			handler = self.name_map.get(data_type)
			if not handler:
				general.log_error("[ map ] unknow packet type",
					data[:2].encode("hex"), data[2:].encode("hex"))
				return
			try:
				handler(self, data_io)
			except:
				general.log_error("[ map ] handle_data error:", data.encode("hex"))
				general.log_error(traceback.format_exc())
				if data_type in DATA_TYPE_CANCEL_TRADE_WHEN_EXCEPT:
					try:
						self.pc.cancel_trade()
					except:
						general.log_error("[ map ] cancel trade when except error:")
						general.log_error(traceback.format_exc())
	
	def send_item_list(self):
		with self.pc.lock:
			self._send_item_list()
	def _send_item_list(self):
		for iid in self.pc.sort.item:
			self.send("0203",
				self.pc.item[iid],
				iid,
				self.pc.get_item_part(iid)
			)
	
	def sync_map(self):
		with self.pc.lock:
			if not self.pc.map_obj:
				return
			with self.pc.map_obj.lock:
				for p in self.pc.map_obj.pc_list:
					if not p.online:
						continue
					if not p.visible:
						continue
					if self.pc == p:
						continue
					general.log("sync_map", self.pc, "<->", p)
					#他キャラ情報→自キャラ
					self.send("120c", p)
					#自キャラ情報→他キャラ
					p.map_send("120c", self.pc)
				for pet in self.pc.map_obj.pet_list:
					if not pet.master:
						continue
					self.send("122f", pet) #pet info
				for monster in self.pc.map_obj.monster_list:
					if monster.hp <= 0:
						continue
					self.send("122a", (monster.id,)) #モンスターID通知
					self.send("1220", monster) #モンスター情報
				for mi in self.pc.map_obj.mapitem_list:
					self.send("07d5", mi) #drop item info
			with usermaps.usermap_list_lock:
				i = self.pc.map_obj.map_id
				for key, value in usermaps.usermap_list.iteritems():
					if value.entrance_map_id != i:
						continue
					self.send("0bb8", value.master) #飛空庭のひも・テント表示
	
	def send_object_detail(self, i):
		if i >= pets.MIN_PET_ID:
			pet = pets.get_pet_from_id(i)
			if not pet:
				return
			if not pet.master:
				return
			self.send("020d", pet) #キャラ情報
			#self.send_map("11f9", self.pc.pet, 0x06) #キャラ移動アナウンス
		else:
			p = users.get_pc_from_id(i)
			if not p:
				return
			with p.lock:
				if not p.online:
					return
				if not p.visible:
					return
				self.send("020d", p) #キャラ情報
				self.send("041b", p) #kanban
	
	def do_000a(self, data_io):
		#接続・接続確認
		data = data_io.read()
		general.log("[ map ] eco version", unpack_unsigned_int(data[:4]))
		self.send("ffff")
		self.send("000b", data)
		self.send("000f", self.word_front+self.word_back)
		general.log("[ map ] send word",
			self.word_front.encode("hex"), self.word_back.encode("hex"),
		)
	
	def do_0032(self, data_io):
		#接続確認(マップサーバとのみ) 20秒一回
		self.send("0033", "ping", "", "") #reply_ping=True
	
	def do_0010(self, data_io):
		#マップサーバーに認証情報の送信
		username = io_unpack_str(data_io)
		password_sha1 = io_unpack_raw(data_io)[:40]
		general.log("[ map ]", "login", username, password_sha1)
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
					self.stop()
					return
				user.reset_map()
				user.map_client = self
				self.user = user
				self.send("0011") #認証結果(マップサーバーに認証情報の送信(s0010)に対する応答)
				break
		else:
			self.stop()
	
	def do_01fd(self, data_io):
		#選択したキャラ番号通知
		unknow = io_unpack_int(data_io)
		if not self.pc:
			num = io_unpack_byte(data_io)
			with self.user.lock:
				if not self.user.pc_list[num]:
					self.stop()
					return
				self.pc = self.user.pc_list[num]
			self.pc.reset_map()
			with self.pc.lock:
				self.pc.online = True
				general.log("[ map ] set", self.pc)
		self.pc.update_status()
		self.pc.set_map()
		self.pc.set_visible(False)
		#self.pc.set_motion(111, False) #motion
		self.pc.set_coord(self.pc.x, self.pc.y) #on login
		if not self.pc.map_obj:
			self.pc.set_map(10023100) #アップタウン東可動橋
			self.pc.set_coord(random.randint(252, 253), random.randint(126, 129))
		
	def do_0037(self, data_io):
		self.send("1f72") #もてなしタイニーアイコン
		self.send("1239", self.pc, 10) #キャラ速度通知・変更 #マップ読み込み中は96
		self.send("0fa7", self.pc) #キャラのモード変更
		self.send("1a5f") #右クリ設定
		self.send_item_list() #インベントリ情報0203
		self.send("03f2", 0x04) #システムメッセージ #構えが「叩き」に変更されました
		self.send("01ff", self.pc) #自分のキャラクター情報
		self.send("1ce8")
		self.send("1d06", 0x0f) #emotion_ex enumerate
		self.send("0230", self.pc) #現在CAPA/PAYL
		self.send("0231", self.pc) #最大CAPA/PAYL
		self.send("0221", self.pc) #最大HP/MP/SP
		self.send("021c", self.pc) #現在のHP/MP/SP/EP
		self.send("157c", self.pc) #キャラの状態
		self.send("0212", self.pc) #ステータス・補正・ボーナスポイント
		self.send("0217", self.pc) #詳細ステータス
		self.send("0223", self.pc) #属性値
		self.send("0226", self.pc, 0) #スキル一覧 一次職
		self.send("0226", self.pc, 1) #スキル一覧 エキスパ
		self.send("022d", self.pc) #HEARTスキル
		self.send("122a") #モンスターID通知
		self.send("0235", self.pc) #EXP/JOBEXP
		self.send("023a", self.pc) #Lv JobLv ボーナスポイント スキルポイント
		self.send("0244", self.pc) #ステータスウィンドウの職業
		self.send("196e", self.pc) #クエスト回数・時間
		self.send("1bbc") #スタンプ帳詳細
		self.send("025d") #不明
		self.send("0695") #不明
		self.send("2260") #2260不明
		self.send("2288") #2288不明
		self.send("0221", self.pc) #最大HP/MP/SP
		self.send("021c", self.pc) #現在のHP/MP/SP/EP
		self.send("0236", self.pc) #wrp ranking関係
		#self.send("196e", self.pc) #クエスト回数・時間
		#self.send("09ec", self.pc) #ゴールド入手
		#self.send("022e", self.pc) #リザーブスキル
		for i in xrange(84):
			self.send("1ce9", i) #useable motion_ex_id
		#self.send("1b67", self.pc) #MAPログイン時に基本情報を全て受信した後に受信される
		general.log("[ map ] send pc info success")
	
	def do_11fe(self, data_io):
		#MAPワープ完了通知
		general.log("[ map ]", "map load")
		self.pc.set_visible(True)
		self.send("09e9", self.pc) #キャラの見た目を変更
		self.send("157c", self.pc) #キャラの状態
		self.send("021c", self.pc) #現在のHP/MP/SP/EP
		self.send("0226", self.pc, 0) #スキル一覧 一次職
		self.send("0226", self.pc, 1) #スキル一覧 エキスパ
		self.send("022d", self.pc) #HEARTスキル
		#2184
		self.send("13ec")
		#self.send("196e", self.pc) #クエスト回数・時間
		self.send("1239", self.pc) #キャラ速度通知・変更
		#self.send("0259", self.pc) #ステータス試算結果
		#self.send("1b67", self.pc) #MAPログイン時に基本情報を全て受信した後に受信される
		
		#self.send("0230", self.pc) #現在CAPA/PAYL
		#self.send("0231", self.pc) #最大CAPA/PAYL
		#self.send("0221", self.pc) #最大HP/MP/SP
		#self.send("0212", self.pc) #ステータス・補正・ボーナスポイント
		#self.send("0217", self.pc) #詳細ステータス
		#self.send("0223", self.pc) #属性値
		#self.send("0244", self.pc) #ステータスウィンドウの職業
		
		self.sync_map()
		self.pc.unset_pet()
		if self.pc.equip.pet:
			time.sleep(0.5) #must have some delay before send 122f (pet info)
		self.pc.set_pet()
		
		if self.send_login_event:
			self.send_login_event = False
			script.run(self.pc, env.LOGIN_EVENT_ID)
		
		if usermaps.map_id_in_range_flygarden(self.pc.map_obj.map_id):
			#bad packet, i dont known the structure of 1be4
			#self.send("1be4", self.pc) #飛空庭ログイン
			#1bf9 only for reply 1bf8, plz remove when 1be4 work
			for i, attr in enumerate(general.FLYGARDEN_ATTR_LIST):
				#飛空庭に装飾品を装着・解除するの結果
				self.send("1bf9", getattr(self.pc.map_obj.flygarden, attr), i)
			self.send("13bc", 2) #飛空庭の天候
			self.send("13bd", 4) #飛空庭の天体
			self.send("1bee", self.pc) #飛空庭の天候
			self.send("1bf0", self.pc) #飛空庭の天候
	
	def do_0fa5(self, data_io):
		#戦闘状態変更通知
		self.pc.set_battlestatus(io_unpack_byte(data_io))
	
	def do_121b(self, data_io):
		#モーションセット＆ログアウト
		motion_id = io_unpack_short(data_io)
		loop = True if io_unpack_byte(data_io) else False
		general.log("[ map ] motion %d loop %s"%(motion_id, loop))
		#self.pc.set_motion(motion_id, loop)
		#self.send_map("121c", self.pc) #モーション通知
		self.pc.set_motion(motion_id, loop)
		if motion_id == 135 and loop: #ログアウト開始
			general.log("[ map ]", "start logout")
			self.send("0020", self.pc, "logoutstart")
			self.pc.logout = True
	
	def do_001c(self, data_io):
		#ログアウト
		self.send("001d")
		
	def do_001e(self, data_io):
		#ログアウト(PASS鍵リセット・マップサーバーとのみ通信)
		general.log("[ map ] logout")
	
	def do_001f(self, data_io):
		#ログアウト開始&ログアウト失敗
		if io_unpack_byte(data_io) == 0:
			general.log("[ map ] logout success")
		else:
			general.log("[ map ] logout failed")
	
	def do_11f8(self, data_io):
		#自キャラの移動
		if self.pc.attack:
			general.log("[ map ] stop attack")
			self.pc.reset_attack()
		rawx = io_unpack_short(data_io)
		rawy = io_unpack_short(data_io)
		rawdir = io_unpack_short(data_io)
		move_type = io_unpack_short(data_io)
		#general.log("[ map ] move rawx %d rawy %d rawdir %d move_type %d"%(
		#	rawx, rawy, rawdir, move_type))
		with self.pc.lock:
			if not self.pc.visible:
				#fix warp coord error when 11f8(move) came after 05e6(event)
				general.log("[ map ] 11f8 ignore")
				return
			old_x, old_y = self.pc.x, self.pc.y
			self.pc.set_raw_coord(rawx, rawy)
			self.pc.set_raw_dir(rawdir)
			new_x, new_y = self.pc.x, self.pc.y
			self.send_map_without_self("11f9", self.pc, move_type) #キャラ移動アナウンス
			if old_x == new_x and old_y == new_y:
				return
			if self.pc.logout:
				general.log("[ map ] logout cancel")
				self.pc.logout = False
				self.send("0020", self.pc, "logoutcancel")
			if self.pc.motion_id != 111:
				self.pc.set_motion(111, True)
			if not self.pc.pet:
				return
			with self.pc.pet.lock:
				if self.pc.pet.standby:
					return
				#pet_x = self.pc.pet.x+(new_x-old_x)
				#pet_y = self.pc.pet.y+(new_y-old_y)
				#self.pc.pet.set_coord(pet_x, pet_y)
				#self.pc.pet.set_coord_from_master()
				self.pc.pet.set_raw_dir(rawdir)
				#self.send_map("11f9", self.pc.pet, 0x06) #キャラ移動アナウンス #歩き
	
	def do_020c(self, data_io):
		#キャラクタ情報要求
		obj_id = io_unpack_int(data_io)
		general.log("[ map ] request object id", obj_id)
		self.send_object_detail(obj_id)
	
	def do_13ba(self, data_io):
		#座る/立つの通知
		if self.pc.motion_id != 135:
			self.pc.set_motion(135, True) #座る
		else:
			self.pc.set_motion(111, True) #立つ
	
	def do_03e8(self, data_io):
		#オープンチャット送信
		message = io_unpack_str(data_io)
		if not script.handle_cmd(self.pc, message):
			self.send_map("03e9", self.pc.id, message) #オープンチャット・システムメッセージ
	
	def do_05e6(self, data_io):
		#イベント実行
		event_id = io_unpack_int(data_io)
		script.run(self.pc, event_id)
	
	def do_05e2(self, data_io):
		#イベント実行
		event_id = io_unpack_int(data_io)
		script.run(self.pc, event_id)
		
	def do_09e2(self, data_io):
		#インベントリ移動
		iid = io_unpack_int(data_io)
		part = io_unpack_byte(data_io)
		count = io_unpack_short(data_io)
		self.pc.unset_equip(iid, part)
	
	def do_09e7(self, data_io):
		#アイテム装備
		iid = io_unpack_int(data_io)
		if self.pc.dem_form_status():
			general.log("[ map ] set equip failed", self.pc)
			self.send("09e8", iid, -1, -2, 1) #アイテム装備
		else:
			self.pc.set_equip(iid)
	
	def do_0a16(self, data_io):
		#トレードキャンセル
		general.log("[ map ] trade: send cancel")
		self.pc.cancel_trade()
	
	def do_0a14(self, data_io):
		#トレードのOK状態
		general.log("[ map ] trade: send ok")
		self.pc.set_trade_ok()
	
	def do_0a15(self, data_io):
		#トレードのTradeを押した際に送信
		general.log("[ map ]","trade: send trade")
		self.pc.set_trade_finish()
	
	def do_0a1b(self, data_io):
		#トレードウィンドウに置いたアイテム・金の情報を送信？
		general.log("[ map ] trade send item list")
		iid_list = io_unpack_array(io_unpack_int, data_io)
		count_list = io_unpack_array(io_unpack_short, data_io)
		gold = io_unpack_int(data_io)
		self.pc.set_trade_list(gold, zip(iid_list, count_list))
	
	def do_09f7(self, data_io):
		#倉庫を閉じる
		general.log("[ map ] warehouse closed")
		self.pc.warehouse_open = None
	
	def do_09fb(self, data_io):
		#倉庫から取り出す
		if len(self.pc.item) >= env.MAX_ITEM_STOCK:
			#倉庫から取り出した時の結果 #キャラのアイテム数が100個を超えてしまうためキャンセルされました
			self.send("09fc", -5)
			return
		item_iid = io_unpack_int(data_io)
		item_count = io_unpack_short(data_io)
		general.log("[ map ] take item from warehouse", item_iid, item_count)
		with self.pc.lock:
			if self.pc.warehouse_open is None:
				#倉庫から取り出した時の結果 #倉庫を開けていません
				self.send("09fc", -1)
				return
			if item_iid not in self.pc.warehouse:
				#倉庫から取り出した時の結果 #指定されたアイテムは存在しません
				self.send("09fc", -2)
				return
			item = self.pc.warehouse[item_iid]
			if item.count < item_count:
				#倉庫から取り出した時の結果 #指定された数量が不正です
				self.send("09fc", -3)
				return
			elif item.count == item_count:
				self.pc.warehouse_pop(item_iid)
			else:
				item.count -= item_count
				script.msg(self.pc, "%sを%s個取り出しました"%(item.name, item_count))
			if item.stock:
				script.item(self.pc, item.item_id, item_count)
			else:
				item_take = general.copy(item)
				item_take.count = item_count
				item_take.warehouse = 0
				self.pc.item_append(item_take)
			#倉庫から取り出した時の結果 #成功
			self.send("09fc", 0)
		self.pc.update_item_status()
	
	def do_09fd(self, data_io):
		#倉庫に預ける
		item_iid = io_unpack_int(data_io)
		item_count = io_unpack_short(data_io)
		general.log("[ map ] store item to warehouse", item_iid, item_count)
		with self.pc.lock:
			if len(self.pc.warehouse) >= env.MAX_WAREHOURSE_STOCK:
				#倉庫に預けた時の結果 倉庫のアイテム数が上限を超えてしまうためキャンセルされました
				self.send("09fe", -4)
				return
			if self.pc.warehouse_open is None:
				#倉庫に預けた時の結果 #倉庫を開けていません
				self.send("09fe", -1)
				return
			if item_iid not in self.pc.item:
				#倉庫に預けた時の結果 #指定されたアイテムは存在しません
				self.send("09fe", -2)
				return
			item = self.pc.item[item_iid]
			if item.count < item_count:
				#倉庫に預けた時の結果 #指定された数量が不正です
				self.send("09fe", -3)
			elif item.count == item_count:
				self.pc.item_pop(item_iid)
			else:
				item.count -= item_count
				self.send("09cf", item, item_iid) #アイテム個数変化
				script.msg(self.pc, "%sを%s個失いました"%(item.name, item_count))
			item_store = general.copy(item)
			item_store.count = item_count
			item_store.warehouse = self.pc.warehouse_open
			self.pc.warehouse_append(item_store)
			#倉庫に預けた時の結果 #成功
			self.send("09fe", 0)
		self.pc.update_item_status()
	
	def do_09c4(self, data_io):
		#アイテム使用
		item_iid = io_unpack_int(data_io)
		target_id = io_unpack_int(data_io)
		x = io_unpack_unsigned_byte(data_io)
		y = io_unpack_unsigned_byte(data_io)
		with self.pc.lock:
			item = self.pc.item.get(item_iid)
			if not item:
				return
			event_id = item.event_id
			item_event_id = item.item_id
			item_skill_id = item.skill_id
			p = self.pc
		if target_id == -1: #対象：地面
			pass
		elif target_id != self.pc.id: #対象：単体
			p = users.get_pc_from_id(target_id)
			if not (p and p.online):
				return
		if event_id:
			script.run(p, event_id, item_event_id)
		else:
			#アイテム使用結果 #success
			self.send("09c5", self.pc, item_event_id, target_id, x, y)
			#アイテム使用効果 (対象：地面)
			self.send("09c6", self.pc, item_event_id, target_id, x, y)
			skills.use(self.pc, target_id, x, y, item_skill_id, 1)
	
	def do_0605(self, data_io):
		#NPCメッセージ(選択肢)の返信
		self.send("0606") #s0605で選択結果が通知された場合の応答
		with self.pc.lock:
			self.pc.select_result = io_unpack_byte(data_io)
	
	def do_05f3(self, data_io):
		#NPCメッセージ(選択肢)の返信
		self.send("05f4") #s0605で選択結果が通知された場合の応答
		with self.pc.lock:
			self.pc.select_result = io_unpack_byte(data_io)
			
	def do_041a(self, data_io):
		#set kanban
		with self.pc.lock:
			self.pc.kanban = io_unpack_str(data_io)
			self.send_map("041b", self.pc)
	
	def do_0617(self, data_io):
		#購入・売却のキャンセル
		with self.pc.lock:
			self.pc.shop_open = None
		general.log("[ map ] npcshop / npcsell close")
	
	def do_0614(self, data_io):
		#NPCショップのアイテム購入
		general.log("[ map ] npcshop")
		with self.pc.lock:
			if self.pc.shop_open is None:
				general.log_error("do_0614: shop_open is None")
				return
			if hasattr(self.pc.shop_open, "__iter__"):
				shop_item_list = self.pc.shop_open
			else:
				shop = db.shop.get(self.pc.shop_open)
				if not shop:
					general.log_error(
						"do_0614 error: shop_id not exist", self.pc.shop_open)
					return
				shop_item_list = shop.item
		item_id_list = io_unpack_array(io_unpack_int, data_io)
		item_count_list = io_unpack_array(io_unpack_int, data_io)
		item_buy_list = zip(item_id_list, item_count_list)
		general.log("[ map ] item_buy_list", item_buy_list)
		if len(self.pc.item)+len(item_buy_list) > env.MAX_ITEM_STOCK:
			script.msg(self.pc, "npcshop buy error: stock limit")
			return
		for item_id, item_count in item_buy_list:
			if not item_count:
				general.log_error("do_0614 error: item_count is 0", item_count)
				continue
			if item_id not in shop_item_list:
				general.log_error("do_0614 error: item_id not in shop_item_list", 
					item_id, shop_item_list)
				continue
			item = db.item.get(item_id)
			if not item:
				general.log_error("do_0614 error: item_id not exist", item_id)
				continue
			if script.takegold(self.pc, (int(item.price/10.0) or 1)*item_count):
				script.item(self.pc, item_id, item_count)
		self.pc.update_item_status()
	
	def do_0616(self, data_io):
		#ショップで売却
		general.log("[ map ] npcsell")
		with self.pc.lock:
			if self.pc.shop_open != 65535:
				general.log_error("do_0616: shop_open != 65535", self.pc.shop_open)
				return
		item_iid_list = io_unpack_array(io_unpack_int, data_io)
		item_count_list = io_unpack_array(io_unpack_int, data_io)
		item_sell_list = zip(item_iid_list, item_count_list)
		general.log("[ map ] item_sell_list", item_sell_list)
		with self.pc.lock:
			for item_iid, item_count in item_sell_list:
				if not item_count:
					general.log_error("do_0616: not item_count", item_count)
					continue
				if self.pc.in_equip(item_iid):
					general.log_error("do_0616: in_equip(item_iid)", item_iid)
					continue
				item = self.pc.item.get(item_iid)
				if not item:
					general.log_error("do_0616: not item", item_iid)
					continue
				if item.count < item_count:
					general.log_error("do_0616: item.count < item_count")
					continue
				if script.gold(self.pc, (int(item.price/100.0) or 1)*item_count):
					if item.count <= item_count:
						self.pc.item_pop(item_iid)
					else:
						item.count -= item_count
						script.msg(self.pc, "%sを%s個失いました"%(
							item.name, item_count
						))
						self.send("09cf", item, item_iid) #アイテム個数変化
		self.pc.update_item_status()
	
	def do_0258(self, data_io):
		#自キャラステータス試算 補正は含まない
		status_num = io_unpack_byte(data_io)
		STR = io_unpack_short(data_io)
		DEX = io_unpack_short(data_io)
		INT = io_unpack_short(data_io)
		VIT = io_unpack_short(data_io)
		AGI = io_unpack_short(data_io)
		MAG = io_unpack_short(data_io)
		nullpc = general.NullClass()
		self.send("0209", STR, DEX, INT, VIT, AGI, MAG) #ステータス上昇s0208の結果
		with self.pc.lock:
			STR += self.pc.stradd
			DEX += self.pc.dexadd
			INT += self.pc.intadd
			VIT += self.pc.vitadd
			AGI += self.pc.agiadd
			MAG += self.pc.magadd
			LV = self.pc.lv_base
			nullpc.status = self.pc.get_status(LV, STR, DEX, INT, VIT, AGI, MAG)
		self.send("0259", nullpc) #ステータス試算結果
	
	def do_0f9f(self, data_io):
		#攻撃
		monster_id = io_unpack_int(data_io)
		monster = monsters.get_monster_from_id(monster_id)
		if not monster:
			general.log_error("[ map ] monster id %s not exist"%monster_id)
			return
		general.log("[ map ] attack monster id %s"%monster_id)
		with self.pc.lock:
			self.pc.attack = True
			self.pc.attack_monster = monster
			self.pc.attack_delay = self.pc.status.delay_attack
		monsters.attack_monster(self.pc, monster)
	
	def do_0f96(self, data_io):
		#攻撃中止？
		general.log("[ map ] stop attack")
		self.pc.reset_attack()
	
	def do_1216(self, data_io):
		#emotion request
		emotion_id = io_unpack_int(data_io)
		self.send_map("1217", self.pc, emotion_id) #emotion
	
	def do_1d0b(self, data_io):
		#emotion_ex request
		emotion_ex_id = io_unpack_byte(data_io)
		self.send_map("1d0c", self.pc, emotion_ex_id) #emotion_ex
	
	def do_1d4c(self, data_io):
		#greeting
		target_id = io_unpack_int(data_io)
		p = users.get_pc_from_id(target_id)
		with self.pc.lock and p.lock:
			rawdir = general.get_angle_from_coord(self.pc.x, self.pc.y, p.x, p.y)
			p_rawdir = general.get_angle_from_coord(p.x, p.y, self.pc.x, self.pc.y)
			if rawdir is None or p_rawdir is None:
				self.pc.set_raw_dir(0.0)
				p.set_raw_dir(180.0)
			else:
				self.pc.set_raw_dir(rawdir)
				p.set_raw_dir(p_rawdir)
		self.send_map("11f9", self.pc, 0x01) #キャラ移動アナウンス 向き変更のみ
		self.send_map("11f9", p, 0x01) #キャラ移動アナウンス 向き変更のみ
		motion = random.choice((113, 163, 164))
		self.pc.set_motion(motion, False)
		p.set_motion(motion, False)
	
	def do_0a0a(self, data_io):
		#send trade ask
		target_id = io_unpack_int(data_io)
		p = users.get_pc_from_id(target_id)
		if not p:
			general.log("[ map ] trade ask: target not exist", target_id)
			self.send("0a0b", -5) #trade ask result, 相手が見つかりません
			return
		with self.pc.lock and p.lock and p.user.lock:
			if not p.online:
				general.log("[ map ] trade ask: target not online", target_id)
				self.send("0a0b", -5) #trade ask result, 相手が見つかりません
				return
			if self.pc.map_id != p.map_id:
				general.log(
					"[ map ] trade ask: target not on the same map", target_id
				)
				self.send("0a0b", -5) #trade ask result, 相手が見つかりません
				return
			if self.pc.trade:
				self.send("0a0b", -1) #trade ask result, トレード中です
				return
			if self.pc.event_id:
				self.send("0a0b", -2) #trade ask result, イベント中です
				return
			if p.trade:
				self.send("0a0b", -3) #trade ask result, 相手がトレード中です
				return
			if p.event_id:
				self.send("0a0b", -4) #trade ask result, 相手がイベント中です
				return
			p.map_send("0a0c", self.pc) #receive trade ask
			self.pc.trade_target_id = p.id
			p.trade_target_id = self.pc.id
	
	def do_0a0d(self, data_io):
		#trade ask answer
		answer = io_unpack_byte(data_io)
		if not self.pc.trade_target_id:
			general.log("[ map ] trade answer: not self.pc.trade_target_id")
			return
		p = self.pc.get_trade_target()
		if not p:
			return
		with self.pc.lock and p.lock and p.user.lock:
			if answer == 0:
				#trade ask result, トレードを断られました
				self.pc.trade_target_id = 0
				p.trade_target_id = 0
				p.map_send("0a0b", -6)
			else:
				self.pc.trade = True
				p.trade = True
				p.map_send("0a0f", self.pc.name) #トレードウィンドウ表示
				self.send("0a0f", p.name) #トレードウィンドウ表示
	
	def do_07d0(self, data_io):
		#put item request
		iid = io_unpack_int(data_io)
		count = io_unpack_short(data_io)
		general.log("[ map ] put item: iid", iid, "count", count)
		with self.pc.lock:
			if self.pc.trade:
				#put item error, トレード中はアイテムを捨てる事が出来ません
				self.send("07d1", -8)
				return
			if self.pc.event_id:
				#put item error, イベント中はアイテムを捨てることが出来ません
				self.send("07d1", -10)
				return
			item, err = script.takeitem_byiid(self.pc, iid, count)
			if err:
				self.send("07d1", err)
				return
			if not item:
				general.log("[ map ] put item: not item but err = 0", iid, count)
				return
			self.pc.map_obj.mapitem_append(item, self.pc.x, self.pc.y, self.pc.id)
		self.pc.update_item_status()
	
	def do_07e4(self, data_io):
		#pick up item request
		mapitem_id = io_unpack_int(data_io)
		general.log("[ map ] pick up item: mapitem_id", mapitem_id)
		if len(self.pc.item) >= env.MAX_ITEM_STOCK:
			script.msg(self.pc, "pick up item error: stock limit")
			return
		with self.pc.lock:
			if self.pc.trade:
				#pick up item error, トレード中はアイテムを拾うことが出来ません
				self.send("07e6", -8)
				return
			if self.pc.event_id:
				#pick up item error, イベント中はアイテムを拾うことが出来ません
				self.send("07e6", -9)
				return
			mapitem_obj = self.pc.map_obj.mapitem_pop(mapitem_id)
			if not mapitem_obj:
				#pick up item error, 存在しないアイテムです
				self.send("07e6", -1)
				return
			self.send_map("07df", mapitem_obj) #pick up item
			item = mapitem_obj.item
			if item.stock:
				script.item(self.pc, item.item_id, item.count)
			else:
				self.pc.item_append(mapitem_obj.item)
		self.pc.update_item_status()
	
	def do_1e7d(self, data_io):
		#DEMのフォームチェンジ
		#point pc.equip to pc.eqiup_dem or pc.equip_std before change
		#if not stable, it will back to unset all equip before change
		status = io_unpack_byte(data_io)
		if self.pc.dem_form_change(status):
			general.log("[ map ] dem form change success")
		else:
			general.log("[ map ] dem form change failed")
	
	def do_1e87(self, data_io):
		#DEMパーツ装着
		#warning: cannot unset parts on dem parts window
		iid = io_unpack_int(data_io)
		if self.pc.dem_form_status():
			self.pc.set_equip(iid)
		else:
			general.log("[ map ] set dem parts failed", self.pc)
			self.send("09e8", iid, -1, -2, 1) #アイテム装備
	
	def do_026c(self, data_io):
		#見た目変更ウィンドウ
		self.send("026d")

	def do_1387(self, data_io):
		#スキル使用
		skill_id = io_unpack_unsigned_short(data_io)
		target_id = io_unpack_int(data_io)
		x = io_unpack_unsigned_byte(data_io)
		y = io_unpack_unsigned_byte(data_io)
		skill_lv = io_unpack_byte(data_io)
		skills.use(self.pc, target_id, x, y, skill_id, skill_lv)

	def do_1cf2(self, data_io):
		#お顔スイッチャー
		self.send("1cf3")

	def do_1cf4(self, data_io):
		#お顔スイッチャー
		iid = io_unpack_int(data_io)
		face_id = io_unpack_unsigned_short(data_io)
		script.takeitem_byiid(self.pc, iid, 1)
		script.face(self.pc, face_id)

	def do_1cf6(self, data_io):
		#お顔スイッチャー
		self.send("1cf7", self.pc, self.pc.face)

	def do_0615(self, data_io):
		#ヘアサロン
		iid = io_unpack_int(data_io)
		hair_id = io_unpack_unsigned_short(data_io)
		wig_id = io_unpack_short(data_io)
		if hair_id != 65535:
			if iid != -1:#オプション変更時
				script.takeitem_byiid(self.pc, iid, 1)
			with self.pc.lock:
				self.pc.hair = hair_id
				self.pc.wig = wig_id
			script.update(self.pc)

	def do_121d(self, data_io):
		"""待機モーション変更"""
		motion = io_unpack_short(data_io)
		self.send("121e", self.pc, motion)


MapDataHandler.name_map = general.get_name_map(MapDataHandler.__dict__, "do_")