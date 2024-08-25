#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
import os
import traceback
import builtins
import codecs
from lib import env



def get_raw_dict(name):
	db_path = dbmap.DATABASE_PATH[name]
	dump_data = general.load_dump(db_path, env.DATABASE_DIR)
	if dump_data is not None and type(dump_data) == dict:
		ver = dump_data.get("ver")
		raw_dict = dump_data.get("raw_dict")
		if ver == env.DATABASE_FORMAT_VERSION:
			if raw_dict is not None and type(raw_dict) == dict:
				return raw_dict
	general.log("Update", name, "database dump ...")
	
	db_file = open(db_path, "rb")
	line_first = db_file.readline()
	db_file.close()

	if name in LOAD_METHOD:
		load_method = LOAD_METHOD[name]
	else:
		load_method = read_encoding

	if line_first.startswith("\xef\xbb\xbf"):
		raw_dict = load_method(name, "utf_8_sig")
	else:
		raw_dict = load_method(name, "cp932")
	
	general.save_dump(
		db_path,
		{"ver": env.DATABASE_FORMAT_VERSION, "raw_dict": raw_dict},
		env.DATABASE_DIR,
	)
	return raw_dict

def read_motion_together(name, enc):
	raw_dict = {}
	db_path = dbmap.DATABASE_PATH[name]
	row_map = {}
	row_map_raw = dbmap.get_row_map_raw(name)
	row_map_ext = dbmap.get_row_map_ext(name)
	min_length = float("-inf")

	with codecs.open(db_path, "r", enc) as db_file:
		for line in db_file:
			if not line.startswith("#"):
				break
			attr_table = line.strip().split(",")
			for i, attr in enumerate(attr_table):
				attr = attr.strip()
				if not attr:
					continue
				value = row_map_raw.get(attr)
				if value is None:
					#general.log_error("attr not define:", attr)
					continue
				if value is NULL:
					continue
				if i > min_length:
					min_length = i
				row_map[i] = value
			#min_length += 1
		row_map.update(row_map_ext)

	with codecs.open(db_path, "r", enc) as db_file:
		for line in db_file:
			if line.startswith("#"):
				continue
			if line in ("\n", "\r\n"):
				continue
			row = line.split(",")
			if len(row) < min_length:
				continue
			d = {}
			for i, value in row_map.iteritems():
				try:
					d[value[1]] = value[0](row[i])
				except:
					general.log_error("attr:", value)
					raise
			if int(row[0]) in raw_dict:
				raw_dict[int(row[0])][int(row[1])] = d
			else:
				t = {}
				t[int(row[1])] = d
				raw_dict[int(row[0])] = t
	return raw_dict

LOAD_METHOD = {
	"partner_motion_together": read_motion_together,
}

def read_encoding(name, enc):
	raw_dict = {}
	db_path = dbmap.DATABASE_PATH[name]
	row_map = {}
	row_map_raw = dbmap.get_row_map_raw(name)
	row_map_ext = dbmap.get_row_map_ext(name)
	min_length = float("-inf")

	with codecs.open(db_path, "r", enc) as db_file:
		for line in db_file:
			if not line.startswith("#"):
				break
			attr_table = line.strip().split(",")
			for i, attr in enumerate(attr_table):
				attr = attr.strip()
				if not attr:
					continue
				value = row_map_raw.get(attr)
				if value is None:
					#general.log_error("attr not define:", attr)
					continue
				if value is NULL:
					continue
				if i > min_length:
					min_length = i
				row_map[i] = value
			#min_length += 1
		row_map.update(row_map_ext)

	with codecs.open(db_path, "r", enc) as db_file:
		for line in db_file:
			if line.startswith("#"):
				continue
			if line in ("\n", "\r\n"):
				continue
			row = line.split(",")
			if len(row) < min_length:
				continue
			d = {}
			for i, value in row_map.iteritems():
				try:
					d[value[1]] = value[0](row[i])
				except:
					general.log_error("attr:", value)
					raise
			raw_dict[int(row[0])] = d
	return raw_dict


def load_database(name, obj):
	db_path = dbmap.DATABASE_PATH[name]
	general.log_line("[load ] load %-20s"%("%s ..."%db_path))
	db_dict = {}
	raw_dict = get_raw_dict(name)
	for i, d in raw_dict.iteritems():
		try:
			db_dict[i] = obj(d)
		except:
			general.log_error("load error: id %s"%str(i), traceback.format_exc())
	general.log("	%d	%s	load."%(len(db_dict), name))
	return db_dict

def load():
	global general, NULL, dbmap
	from lib import general
	from lib.general import NULL
	from lib import dbmap
	import data.item, data.job, data.npc, data.shop, data.skill, data.motion2
	import obj.map, obj.monster, obj.pet
	
	global item, job, map_obj, monster_obj, npc, pet_obj, partner_obj, shop, skill, partner_motion_together
	item = load_database("item", data.item.Item)
	item_tmp = load_database("item3", data.item.Item)
	item.update(item_tmp)
	item_tmp = load_database("item7", data.item.Item)
	item.update(item_tmp)

	job = load_database("job", data.job.Job)
	map_obj = load_database("map", obj.map.Map)
	monster_obj = load_database("monster", obj.monster.Monster)
	npc = load_database("npc", data.npc.Npc)
	pet_obj = load_database("pet", obj.pet.Pet)
	partner_obj = load_database("partner", obj.pet.Pet)
	partner_motion_together = load_database("partner_motion_together", data.motion2.Motion2)
	shop = load_database("shop", data.shop.Shop)
	skill = load_database("skill", data.skill.Skill)
