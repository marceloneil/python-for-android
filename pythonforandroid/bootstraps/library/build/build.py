#!/usr/bin/env python2.7
# coding: utf-8

from __future__ import print_function
from os.path import (
    dirname, join, isfile, realpath, relpath, split, exists, basename)
from os import makedirs, remove, listdir
import os
import tarfile
import time
import subprocess
import shutil
from zipfile import ZipFile
import sys
from distutils.version import LooseVersion

from fnmatch import fnmatch

import jinja2

curdir = dirname(__file__)

# Try to find a host version of Python that matches our ARM version.
PYTHON = join(curdir, 'python-install', 'bin', 'python.host')
if not exists(PYTHON):
    print('Could not find hostpython, will not compile to .pyo (this is normal with python3)')
    PYTHON = None

BLACKLIST_PATTERNS = [
    # code versionning
    '^*.hg/*',
    '^*.git/*',
    '^*.bzr/*',
    '^*.svn/*',

    # pyc/py
    '*.pyc',

    # temp files
    '~',
    '*.bak',
    '*.swp',

    # buildozer
    '^*.buildozer/*',
]
if PYTHON is not None:
    BLACKLIST_PATTERNS.append('*.py')

#WHITELIST_PATTERNS = ['pyconfig.h', ]
WHITELIST_PATTERNS = []

python_files = []

def try_unlink(fn):
    if exists(fn):
        os.unlink(fn)


def ensure_dir(path):
    if not exists(path):
        makedirs(path)

def is_whitelist(name):
    return match_filename(WHITELIST_PATTERNS, name)


def is_blacklist(name):
    if is_whitelist(name):
        return False
    return match_filename(BLACKLIST_PATTERNS, name)


def match_filename(pattern_list, name):
    for pattern in pattern_list:
        if pattern.startswith('^'):
            pattern = pattern[1:]
        else:
            pattern = '*/' + pattern
        if fnmatch(name, pattern):
            return True


def listfiles(d):
    basedir = d
    subdirlist = []
    for item in os.listdir(d):
        fn = join(d, item)
        if os.path.islink(fn):
            continue
        if isfile(fn):
            yield fn
        else:
            subdirlist.append(join(basedir, item))
    for subdir in subdirlist:
        for fn in listfiles(subdir):
            yield fn


def make_python_zip():
    '''
    Search for all the python related files, and construct the pythonXX.zip
    According to
    # http://randomsplat.com/id5-cross-compiling-python-for-embedded-linux.html
    site-packages, config and lib-dynload will be not included.
    '''

    if not exists('private'):
        print('No compiled python is present to zip, skipping.')
        print('this should only be the case if you are using the CrystaX python')
        return

    global python_files
    d = realpath(join('private', 'lib', 'python2.7'))

    def select(fn):
        if is_blacklist(fn):
            return False
        fn = realpath(fn)
        assert(fn.startswith(d))
        fn = fn[len(d):]
        if (fn.startswith('/site-packages/') or
            fn.startswith('/config/') or
            fn.startswith('/lib-dynload/') or
            fn.startswith('/libpymodules.so')):
            return False
        return fn

    # get a list of all python file
    python_files = [x for x in listfiles(d) if select(x)]

    # create the final zipfile
    zfn = join('private', 'lib', 'python27.zip')
    zf = ZipFile(zfn, 'w')

    # put all the python files in it
    for fn in python_files:
        afn = fn[len(d):]
        zf.write(fn, afn)
    zf.close()


def make_tar(tfn, source_dirs, ignore_path=[]):
    '''
    Make a zip file `fn` from the contents of source_dis.
    '''

    # selector function
    def select(fn):
        rfn = realpath(fn)
        for p in ignore_path:
            if p.endswith('/'):
                p = p[:-1]
            if rfn.startswith(p):
                return False
        if rfn in python_files:
            return False
        return not is_blacklist(fn)

    # get the files and relpath file of all the directory we asked for
    files = []
    for sd in source_dirs:
        sd = realpath(sd)
        compile_dir(sd)
        files += [(x, relpath(realpath(x), sd)) for x in listfiles(sd)
                  if select(x)]

    # create tar.gz of thoses files
    tf = tarfile.open(tfn, 'w:gz', format=tarfile.USTAR_FORMAT)
    dirs = []
    for fn, afn in files:
#        print('%s: %s' % (tfn, fn))
        dn = dirname(afn)
        if dn not in dirs:
            # create every dirs first if not exist yet
            d = ''
            for component in split(dn):
                d = join(d, component)
                if d.startswith('/'):
                    d = d[1:]
                if d == '' or d in dirs:
                    continue
                dirs.append(d)
                tinfo = tarfile.TarInfo(d)
                tinfo.type = tarfile.DIRTYPE
                tf.addfile(tinfo)

        # put the file
        tf.add(fn, afn)
    tf.close()


def compile_dir(dfn):
    '''
    Compile *.py in directory `dfn` to *.pyo
    '''
    # -OO = strip docstrings
    if PYTHON is None:
        return
    subprocess.call([PYTHON, '-OO', '-m', 'compileall', '-f', dfn])


def make_package(args):
    # Ignore warning if the launcher is in args
    # Delete the old assets.
    try_unlink('src/main/assets/public.mp3')
    try_unlink('src/main/assets/private.mp3')

    # In order to speedup import and initial depack,
    # construct a python27.zip
    make_python_zip()

    # Package up the private data (public not supported).
    tar_dirs = [args.private]
    if exists('private'):
        tar_dirs.append('private')
    if exists('crystax_python'):
        tar_dirs.append('crystax_python')

    if args.private:
        make_tar('src/main/assets/private.mp3', tar_dirs, args.ignore_path)
    elif args.launcher:
        # clean 'None's as a result of main.py path absence
        tar_dirs = [tdir for tdir in tar_dirs if tdir]
        make_tar('src/main/assets/private.mp3', tar_dirs, args.ignore_path)

    # folder name for launcher
    url_scheme = 'kivy'



def parse_args(args=None):
    global BLACKLIST_PATTERNS, WHITELIST_PATTERNS, PYTHON
    default_android_api = 12
    import argparse
    ap = argparse.ArgumentParser(description='''\
Package a Python application for Android.

For this to work, Java and Ant need to be in your path, as does the
tools directory of the Android SDK.
''')

    ap.add_argument('--private', dest='private',
                    help='the dir of user files')
                    # , required=True) for launcher, crashes in make_package
                    # if not mentioned (and the check is there anyway)
    #ap.add_argument('--package', dest='package',
    #                help=('The name of the java package the project will be'
    #                      ' packaged under.'),
    #                required=True)
    #ap.add_argument('--name', dest='name',
    #                help=('The human-readable name of the project.'),
    #                required=True)
    ap.add_argument('--numeric-version', dest='numeric_version',
                    help=('The numeric version number of the project. If not '
                          'given, this is automatically computed from the '
                          'version.'))
    #ap.add_argument('--version', dest='version',
    #                help=('The version number of the project. This should '
    #                      'consist of numbers and dots, and should have the '
    #                      'same number of groups of numbers as previous '
    #                      'versions.'),
    #                required=True)
    ap.add_argument('--orientation', dest='orientation', default='portrait',
                    help=('The orientation that the game will display in. '
                          'Usually one of "landscape", "portrait", '
                          '"sensor", or "user" (the same as "sensor" but '
                          'obeying the user\'s Android rotation setting). '
                          'The full list of options is given under '
                          'android_screenOrientation at '
                          'https://developer.android.com/guide/topics/manifest/'
                          'activity-element.html'))
    ap.add_argument('--launcher', dest='launcher', action='store_true',
                    help=('Provide this argument to build a multi-app '
                          'launcher, rather than a single app.'))
    ap.add_argument('--icon', dest='icon',
                    help='A png file to use as the icon for the application.')
    ap.add_argument('--permission', dest='permissions', action='append',
                    help='The permissions to give this app.', nargs='+')
    ap.add_argument('--meta-data', dest='meta_data', action='append',
                    help='Custom key=value to add in application metadata')
    ap.add_argument('--presplash', dest='presplash',
                    help=('A jpeg file to use as a screen while the '
                          'application is loading.'))
    ap.add_argument('--presplash-color', dest='presplash_color', default='#000000',
                    help=('A string to set the loading screen background color. '
                          'Supported formats are: #RRGGBB #AARRGGBB or color names '
                          'like red, green, blue, etc.'))
    ap.add_argument('--wakelock', dest='wakelock', action='store_true',
                    help=('Indicate if the application needs the device '
                          'to stay on'))
    ap.add_argument('--window', dest='window', action='store_true',
                    help='Indicate if the application will be windowed')
    ap.add_argument('--blacklist', dest='blacklist',
                    default=join(curdir, 'blacklist.txt'),
                    help=('Use a blacklist file to match unwanted file in '
                          'the final APK'))
    ap.add_argument('--whitelist', dest='whitelist',
                    default=join(curdir, 'whitelist.txt'),
                    help=('Use a whitelist file to prevent blacklisting of '
                          'file in the final APK'))
    ap.add_argument('--add-jar', dest='add_jar', action='append',
                    help=('Add a Java .jar to the libs, so you can access its '
                          'classes with pyjnius. You can specify this '
                          'argument more than once to include multiple jars'))
    ap.add_argument('--add-aar', dest='add_aar', action='append',
                    help=('Add an aar dependency manually'))
    ap.add_argument('--depend', dest='depends', action='append',
                    help=('Add a external dependency '
                          '(eg: com.android.support:appcompat-v7:19.0.1)'))
    ## The --sdk option has been removed, it is ignored in favour of
    ## --android-api handled by toolchain.py
    ap.add_argument('--sdk', dest='sdk_version', default=-1,
                    type=int, help=('Deprecated argument, does nothing'))
    ap.add_argument('--minsdk', dest='min_sdk_version',
                    default=default_android_api, type=int,
                    help=('Minimum Android SDK version to use. Default to '
                          'the value of ANDROIDAPI, or {} if not set'
                          .format(default_android_api)))
    ap.add_argument('--intent-filters', dest='intent_filters',
                    help=('Add intent-filters xml rules to the '
                          'AndroidManifest.xml file. The argument is a '
                          'filename containing xml. The filename should be '
                          'located relative to the python-for-android '
                          'directory'))
    ap.add_argument('--service', dest='services', action='append',
                    help='Declare a new service entrypoint: '
                         'NAME:PATH_TO_PY[:foreground]')
    ap.add_argument('--add-source', dest='extra_source_dirs', action='append',
                    help='Include additional source dirs in Java build')
    ap.add_argument('--try-system-python-compile', dest='try_system_python_compile',
                    action='store_true',
                    help='Use the system python during compileall if possible.')
    ap.add_argument('--no-compile-pyo', dest='no_compile_pyo', action='store_true',
                    help='Do not optimise .py files to .pyo.')
    ap.add_argument('--sign', action='store_true',
                    help=('Try to sign the APK with your credentials. You must set '
                          'the appropriate environment variables.'))
    ap.add_argument('--add-activity', dest='add_activity', action='append',
                    help='Add this Java class as an Activity to the manifest.')

    if args is None:
        args = sys.argv[1:]
    args = ap.parse_args(args)
    args.ignore_path = []

    #if args.name and args.name[0] == '"' and args.name[-1] == '"':
    #    args.name = args.name[1:-1]

    # if args.sdk_version == -1:
    #     args.sdk_version = args.min_sdk_version

    if args.sdk_version != -1:
        print('WARNING: Received a --sdk argument, but this argument is '
              'deprecated and does nothing.')

    if args.permissions is None:
        args.permissions = []
    elif args.permissions:
        if isinstance(args.permissions[0], list):
            args.permissions = [p for perm in args.permissions for p in perm]

    if args.meta_data is None:
        args.meta_data = []

    if args.services is None:
        args.services = []

    if args.try_system_python_compile:
        # Hardcoding python2.7 is okay for now, as python3 skips the
        # compilation anyway
        if not exists('crystax_python'):
            python_executable = 'python2.7'
            try:
                subprocess.call([python_executable, '--version'])
            except (OSError, subprocess.CalledProcessError):
                pass
            else:
                PYTHON = python_executable

    if args.no_compile_pyo:
        PYTHON = None
        BLACKLIST_PATTERNS.remove('*.py')

    if args.blacklist:
        with open(args.blacklist) as fd:
            patterns = [x.strip() for x in fd.read().splitlines()
                        if x.strip() and not x.strip().startswith('#')]
        BLACKLIST_PATTERNS += patterns

    if args.whitelist:
        with open(args.whitelist) as fd:
            patterns = [x.strip() for x in fd.read().splitlines()
                        if x.strip() and not x.strip().startswith('#')]
        WHITELIST_PATTERNS += patterns

    make_package(args)

    return args


if __name__ == "__main__":
    parse_args()
