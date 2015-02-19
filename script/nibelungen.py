#!/usr/bin/env python
# -*- coding: utf-8 -*-
from lib import script
import random
rand = random.randint
ID = 11000115

def main(pc):
	result = script.select(pc, (
		"use catalog",
		"change option",
		"change(dummy)",
		"view catalog",
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
