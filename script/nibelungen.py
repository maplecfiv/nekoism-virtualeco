#!/usr/bin/env python
# -*- coding: utf-8 -*-
from lib import script
import random
rand = random.randint
ID = 11000115

HAIR_MAP= (
	("リファインナチュラル",200),
	("リファインアンティーク",201),
	("リファインレイヤー",202),
	("リファインショート",203),
	("リファイン外巻きヘア",204),
	("リファイン内巻きヘア",205),
	("リファインセミロング",206),
	("リファインロング",207),
	("リファインベリーショート",208),
	)
def main(pc):
	result = script.select(pc, (
		"use catalog",
		"change option",
		"change(dummy)",
		"view catalog",
		"refine",
		"cancel",
	), "select")
	if result == 1:
		pc.map_send("0614", 0)
	elif result == 2:
		pc.map_send("0614", 1)
	#elif result == 3:
	#	script.help(pc)
	elif result == 4:
		pc.map_send("0614", 2)
	elif result == 5:
		refine(pc)

def refine(pc):
	r = script.select(pc, tuple(i[0] for i in HAIR_MAP)+("cancel",), "refine_hair")
	if r-1 == len(HAIR_MAP):
		return
	with pc.lock:
		pc.hair = HAIR_MAP[r-1][1]
		pc.wig = -1
	script.update(pc)
	pc.map_send("0210", pc)

