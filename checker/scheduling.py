"""Windows Task Scheduler XML drafts only. Never registers, enables or changes a real task."""
from __future__ import annotations

from datetime import datetime
import getpass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

NAMESPACE = 'http://schemas.microsoft.com/windows/2004/02/mit/task'


def launch_spec():
    """Absolute launch paths: frozen portable EXE or this project's Python; no shell/PowerShell wrapper."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve(), ()
    executable = Path(sys.executable).resolve()
    windowless = executable.with_name('pythonw.exe')
    if os.name == 'nt' and windowless.is_file():
        executable = windowless
    return executable, (str(Path(__file__).resolve().parent.parent / 'app.py'),)


def task_xml(data_dir, output_dir, at, *, principal=None, now=None, executable=None, prefix=None):
    """Daily InteractiveToken task: existing logged-in user, least privilege, no saved password.

    StartWhenAvailable requests a delayed run when available, not reconstruction of every missed calendar day.
    Generates only XML bytes. Actual Windows registration/activation is a separate user-approved operation.
    """
    if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', at):
        raise ValueError('Enter a local time as HH:MM (00:00–23:59).')
    data_dir, output_dir = Path(data_dir).resolve(), Path(output_dir).resolve()
    if not data_dir.is_dir() or not output_dir.is_dir():
        raise ValueError('Choose existing application-data and report folders.')
    command, base_args = launch_spec()
    command = Path(executable).resolve() if executable is not None else command
    base_args = tuple(prefix) if prefix is not None else base_args
    if not command.is_file():
        raise ValueError('The launch executable does not exist.')
    principal = principal or ((os.environ.get('USERDOMAIN', '') + '\\' + getpass.getuser()).lstrip('\\'))
    if not principal.strip() or any(c in principal for c in '\r\n\0'):
        raise ValueError('A valid current Windows user is required.')
    now = now or datetime.now()
    boundary = now.replace(hour=int(at[:2]), minute=int(at[3:]), second=0, microsecond=0).isoformat()
    ET.register_namespace('', NAMESPACE)
    tag = lambda name: '{' + NAMESPACE + '}' + name
    root = ET.Element(tag('Task'), version='1.2')
    def add(parent, name, text=None, **attrs):
        node = ET.SubElement(parent, tag(name), attrs)
        if text is not None: node.text = str(text)
        return node
    info = add(root, 'RegistrationInfo')
    add(info, 'Description', 'Auraplex daily summary. Local file verification only; Cloud Not Verified. '
        'Requires this user logged in and Drive mounted. No historical cached fallback.')
    identity = hashlib.sha256(str(data_dir).encode()).hexdigest()[:10]
    add(info, 'URI', '\\Auraplex\\DailySummary-' + identity)
    triggers = add(root, 'Triggers'); trigger = add(triggers, 'CalendarTrigger')
    add(trigger, 'StartBoundary', boundary); add(trigger, 'Enabled', 'true')
    add(add(trigger, 'ScheduleByDay'), 'DaysInterval', '1')
    person = add(add(root, 'Principals'), 'Principal', id='Author')
    add(person, 'UserId', principal); add(person, 'LogonType', 'InteractiveToken'); add(person, 'RunLevel', 'LeastPrivilege')
    settings = add(root, 'Settings')
    for name, value in (('MultipleInstancesPolicy','IgnoreNew'), ('StartWhenAvailable','true'),
                        ('DisallowStartIfOnBatteries','true'), ('StopIfGoingOnBatteries','false'),
                        ('WakeToRun','false'), ('ExecutionTimeLimit','PT10M'), ('Enabled','true')):
        add(settings, name, value)
    action = add(add(root, 'Actions', Context='Author'), 'Exec')
    # Application receipts make retries explicit and bounded. Do not multiply them
    # with RestartOnFailure, whose native restart was not observed in OS probes.
    args = (*base_args, '--daily-run', str(output_dir), '--data-dir', str(data_dir),
            '--daily-attempts', '3', '--daily-retry-delay', '30')
    add(action, 'Command', str(command)); add(action, 'Arguments', subprocess.list2cmdline(args))
    add(action, 'WorkingDirectory', str(command.parent))
    return ET.tostring(root, encoding='utf-16', xml_declaration=True)
