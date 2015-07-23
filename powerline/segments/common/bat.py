# encoding=utf8
from __future__ import (unicode_literals, division, absolute_import, print_function)

import os
import sys
import re

from powerline.lib.shell import run_cmd


# XXX Warning: module name must not be equal to the segment name as long as this 
# segment is imported into powerline.segments.common module.

def _get_battery_status(pl):
	try:
		import dbus
	except ImportError:
		pl.error('Not using DBUS+UPower as dbus is not available')
	else:
		try:
			bus = dbus.SystemBus()
		except Exception as e:
			pl.exception('Failed to connect to system bus: {0}', str(e))
		else:
			interface = 'org.freedesktop.UPower'
			try:
				up = bus.get_object(interface, '/org/freedesktop/UPower')
			except dbus.exceptions.DBusException as e:
				if getattr(e, '_dbus_error_name', '').endswith('ServiceUnknown'):
					pl.debug('Not using DBUS+UPower as UPower is not available via dbus')
				else:
					pl.exception('Failed to get UPower service with dbus: {0}', str(e))
			else:
				devinterface = 'org.freedesktop.DBus.Properties'
				devtype_name = interface + '.Device'
				for devpath in up.EnumerateDevices(dbus_interface=interface):
					dev = bus.get_object(interface, devpath)
					devget = lambda what: dev.Get(
						devtype_name,
						what,
						dbus_interface=devinterface
					)
					if int(devget('Type')) != 2:
						pl.debug('Not using DBUS+UPower with {0}: invalid type', devpath)
						continue
					if not bool(devget('IsPresent')):
						pl.debug('Not using DBUS+UPower with {0}: not present', devpath)
						continue
					if not bool(devget('PowerSupply')):
						pl.debug('Not using DBUS+UPower with {0}: not a power supply', devpath)
						continue
					pl.debug('Using DBUS+UPower with {0}', devpath)
					return float(
						dbus.Interface(dev, dbus_interface=devinterface).Get(
							devtype_name,
							'Percentage'
						),
						bool(
							dbus.Interface(dev, dbus_interface=devinterface).Get(
								devtype_name,
								'State'
							) == 1
						)
					)
				pl.debug('Not using DBUS+UPower as no batteries were found')

	if os.path.isdir('/sys/class/power_supply'):
		linux_bat_fmt = '/sys/class/power_supply/{0}/capacity'
		for linux_bat in os.listdir('/sys/class/power_supply'):
			cap_path = linux_bat_fmt.format(linux_bat)
			if linux_bat.startswith('BAT') and os.path.exists(cap_path):
				pl.debug('Using /sys/class/power_supply with battery {0}', linux_bat)
				with open(cap_path, 'r') as f:
					_capacity = int(float(f.readline().split()[0]))

		linux_ac_fmt = '/sys/class/power_supply/{0}/online'
		for linux_ac in os.listdir('/sys/class/power_supply'):
			online_path = linux_ac_fmt.format(linux_ac)
			if linux_ac.startswith('AC') and os.path.exists(online_path):
				pl.debug('Using /sys/class/power_supply with ac {0}', linux_ac)
				with open(online_path, 'r') as f:
					_ac_powered = bool(f.readline())
		if _capacity is not None and _ac_powered is not None:
			return _capacity, _ac_powered
		else:
			pl.debug('Not using /sys/class/power_supply as no batteries were found')
	else:
		pl.debug('Not using /sys/class/power_supply: no directory')

	try:
		from shutil import which  # Python-3.3 and later
	except ImportError:
		pl.info('Using dumb “which” which only checks for file in /usr/bin')
		which = lambda f: (lambda fp: os.path.exists(fp) and fp)(os.path.join('/usr/bin', f))

	if which('pmset'):
		pl.debug('Using pmset')

		BATTERY_PERCENT_RE = re.compile(r'(\d+)%')

		battery_summary = run_cmd(pl, ['pmset', '-g', 'batt'])
		battery_percent = BATTERY_PERCENT_RE.search(battery_summary).group(1)
		return int(battery_percent), 'AC' in battery_summary

	else:
		pl.debug('Not using pmset: executable not found')

	if sys.platform.startswith('win') or sys.platform == 'cygwin':
		# From http://stackoverflow.com/a/21083571/273566, reworked
		try:
			from win32com.client import GetObject
		except ImportError:
			pl.debug('Not using win32com.client as it is not available')
		else:
			try:
				wmi = GetObject('winmgmts:')
			except Exception as e:
				pl.exception('Failed to run GetObject from win32com.client: {0}', str(e))
			else:
				for battery in wmi.InstancesOf('Win32_Battery'):
					pl.debug('Using win32com.client with Win32_Battery')
					# http://msdn.microsoft.com/en-us/library/aa394074(v=vs.85).aspx
					return battery.EstimatedChargeRemaining, battery.BatteryStatus == 6
				pl.debug('Not using win32com.client as no batteries were found')
		from ctypes import Structure, c_byte, c_ulong, byref
		if sys.platform == 'cygwin':
			pl.debug('Using cdll to communicate with kernel32 (Cygwin)')
			from ctypes import cdll
			library_loader = cdll
		else:
			pl.debug('Using windll to communicate with kernel32 (Windows)')
			from ctypes import windll
			library_loader = windll

		class PowerClass(Structure):
			_fields_ = [
				('ACLineStatus', c_byte),
				('BatteryFlag', c_byte),
				('BatteryLifePercent', c_byte),
				('Reserved1', c_byte),
				('BatteryLifeTime', c_ulong),
				('BatteryFullLifeTime', c_ulong)
			]

		powerclass = PowerClass()
		result = library_loader.kernel32.GetSystemPowerStatus(byref(powerclass))
		# http://msdn.microsoft.com/en-us/library/windows/desktop/aa372693(v=vs.85).aspx
		if result:
			pl.debug('Not using GetSystemPowerStatus because it failed')
		else:
			pl.debug('Using GetSystemPowerStatus')
			return powerclass.BatteryLifePercent, powerclass.ACLineStatus == 1

	raise NotImplementedError


def battery(pl, format='{capacity:3.0%}', steps=5, gamify=False, full_heart='O', empty_heart='O', charging='C'):
	'''Return battery charge status.

	:param str format:
		Percent format in case gamify is False.
	:param int steps:
		Number of discrete steps to show between 0% and 100% capacity if gamify
		is True.
	:param bool gamify:
		Measure in hearts (♥) instead of percentages. For full hearts 
		``battery_full`` highlighting group is preferred, for empty hearts there 
		is ``battery_empty``.
	:param str full_heart:
		Heart displayed for “full” part of battery.
	:param str empty_heart:
		Heart displayed for “used” part of battery. It is also displayed using
		another gradient level and highlighting group, so it is OK for it to be 
		the same as full_heart as long as necessary highlighting groups are 
		defined.
	:param str charging:
		Indication of "AC charging"

	``battery_gradient`` and ``battery`` groups are used in any case, first is 
	preferred.

	Highlight groups used: ``battery_full`` or ``battery_gradient`` (gradient) or ``battery``, ``battery_empty`` or ``battery_gradient`` (gradient) or ``battery``.
	'''
	try:
		capacity, ac_powered = _get_battery_status(pl)
	except NotImplementedError:
		pl.info('Unable to get battery status.')
		return None

	ret = []
	if gamify:
		denom = int(steps)
		numer = int(denom * capacity / 100)
		ret.append({
			'contents': full_heart * numer,
			'draw_inner_divider': False,
			'highlight_groups': ['battery_full', 'battery_gradient', 'battery'],
			# Using zero as “nothing to worry about”: it is least alert color.
			'gradient_level': 0,
		})
		ret.append({
			'contents': empty_heart * (denom - numer),
			'draw_inner_divider': False,
			'highlight_groups': ['battery_empty', 'battery_gradient', 'battery'],
			# Using a hundred as it is most alert color.
			'gradient_level': 100,
		})
	else:
		ret.append({
			'contents': (charging + ' ' if ac_powered else '') + format.format(capacity=(capacity / 100.0)),
			'highlight_groups': ['battery_gradient', 'battery'],
			# Gradients are “least alert – most alert” by default, capacity has 
			# the opposite semantics.
			'gradient_level': 100 - capacity,
		})
	return ret
