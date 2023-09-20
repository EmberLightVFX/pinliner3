#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import os
import pathlib
import sys
from dataclasses import dataclass
from typing import TextIO

__version__ = "3"

TEMPLATE_FILE = "importer.template"
TEMPLATE_PATTERN = "${CONTENTS}"


@dataclass
class DefArgs:
    set_hook: bool
    tagging: bool
    outfile: TextIO
    default_package: str
    packages: list[str]
    default_pkg: str


def output(cfg: type[DefArgs], what: str, newline: bool = True) -> None:
    # We need indentation for PEP8
    cfg.outfile.write(what)
    if newline:
        cfg.outfile.write(os.linesep)


def process_file(
    cfg: type[DefArgs], base_dir: str, package_path: str
) -> tuple[bool, str]:
    # Replace all pathsep and . with __ to not break variable names
    path = os.path.splitext(package_path)[0].replace(os.path.sep, ".")
    path = os.path.splitext(package_path)[0].replace(os.path.sep, ".")
    full_path = os.path.join(base_dir, package_path)

    print(f"Processing {full_path}")
    output(cfg, f'"{path}": """')
    with open(full_path, "r", encoding="utf-8") as f:
        # Read the whole file
        code = f.read()

        # Insert escape character before """ since we'll be using """ to insert
        # the code as a string
        output(cfg, code.replace('"""', r'\"""'))
    output(cfg, '""",')
    # package_end = cfg.outfile.tell()
    is_package = bool(path.endswith("__init__"))
    if is_package:
        path = path[:-9]

    return is_package, path


def template(cfg: type[DefArgs]) -> str:
    template_path = os.path.join(os.path.dirname(__file__), TEMPLATE_FILE)
    template = pathlib.Path(template_path).read_text()
    prefix_end = template.index(TEMPLATE_PATTERN)
    prefix_data = template[:prefix_end].replace("%{FORCE_EXC_HOOK}", str(cfg.set_hook))
    prefix_data = prefix_data.replace("%{DEFAULT_PACKAGE}", cfg.default_package)
    cfg.outfile.write(prefix_data)
    postfix_begin = prefix_end + len(TEMPLATE_PATTERN)
    return template[postfix_begin:]


def process_directory(
    cfg: type[DefArgs], base_dir: str, package_path: str
) -> list[tuple[bool, str]]:
    file_vars: list[tuple[bool, str]] = []
    contents = os.listdir(os.path.join(base_dir, package_path))
    for content in contents:
        next_path = os.path.join(package_path, content)
        path = os.path.join(base_dir, next_path)
        if is_module(path):
            file_vars.append(process_file(cfg, base_dir, next_path))
        elif is_package(path):
            file_vars.extend(process_directory(cfg, base_dir, next_path))
    return file_vars


def process_files(cfg: type[DefArgs]) -> None:
    # template would look better as a context manager
    postfix = template(cfg)
    file_vars: list[tuple[bool, str]] = []
    output(cfg, 2 * os.linesep + "data = {")
    for package_path in cfg.packages:
        base_dir, module_name = os.path.split(package_path)
        file_vars.extend(process_directory(cfg, base_dir, module_name))
    output(cfg, 2 * os.linesep + "}")

    output(cfg, 2 * os.linesep + "inliner_packages = {")
    for var in file_vars:
        data = {"is_package": var[0], "data": var[1]}
        output(cfg, f'"{var[1]}": {data},')
    output(cfg, 2 * os.linesep + "}")
    # No newline on last line, as we want output file to be PEP8 compliant.
    output(cfg, postfix, newline=False)
    cfg.outfile.close()


def parse_args() -> type[DefArgs]:
    class MyParser(argparse.ArgumentParser):
        """Class to print verbose help on error."""

        def error(self, message: str):
            self.print_help()
            sys.stderr.write(f"\nERROR: {message}\n")
            sys.exit(2)

    general_description = f"""
Pinliner3 - Python Inliner (Version {__version__})

    This tool allows you to merge all files that comprise a Python package into
a single file and be able to use this single file as if it were a package.

    Imports will work as usual so if you have a package structure like:
        .
        └── [my_package]
             ├── file_a.py
             ├── [sub_package]
             │    ├── file_b.py
             │    └── __init__.py
             ├── __init__.py

    And you execute:
        $ mkdir test
        $ pinliner3 my_package test/my_package.py
        $ cd test
        $ python

    You'll be able to use this file as if it were the real package:
        >>> import my_package
        >>> from my_package import file_a as a_file
        >>> from my_package.sub_package import file_b

    And __init__.py contents will be executed as expected when importing
my_package and you'll be able to access its contents like you would with your
normal package.  Modules will also behave as usual.

    By default there is no visible separation between the different modules'
source code, but one can be enabled for clarity with option --tag, which will
include a newline and a <tag:file_path> tag before each of the source files.
"""
    general_epilog = None

    parser = MyParser(
        description=general_description,
        epilog=general_epilog,
        argument_default="",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "packages",
        nargs="+",
        help="Packages to inline.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=__version__,
    )
    parser.add_argument(
        "-o",
        "--outfile",
        nargs="?",
        dest="outfile",
        type=lambda x: open(x, "w", encoding="utf-8"),
        default=sys.stdout,
        help="Output file.",
    )
    parser.add_argument(
        "--set-except",
        default=None,
        dest="set_hook",
        action="store_true",
        help="Force setting handler for uncaught exceptions.",
    )
    parser.add_argument(
        "--no-except",
        default=None,
        dest="set_hook",
        action="store_false",
        help="Don't set handler for uncaught exceptions.",
    )
    parser.add_argument(
        "--tag",
        default=False,
        dest="tagging",
        action="store_true",
        help="Mark with <tag:file_path> each added file.",
    )
    parser.add_argument(
        "-d",
        "--default-pkg",
        default="",
        dest="default_package",
        help="Define the default package when multiple packages are inlined.",
    )

    cfg = parser.parse_args(namespace=DefArgs)

    # If user didn't pass a default package determine one ourselves.
    if cfg.default_package == "":
        # For single package file default is the package, for multiple packaged
        # files default is none (act as a bundle).
        def_file = cfg.packages[0] if len(cfg.packages) == 1 else ""
        cfg.default_package = str(def_file)
    return cfg


def is_module(module: str):
    # This validation is poor, but good enough for now
    return os.path.isfile(module) and module.endswith(".py")


def is_package(package: str):
    init_file = os.path.join(package, "__init__.py")
    return os.path.isdir(package) and os.path.isfile(init_file)


def validate_args(cfg: type[DefArgs]):
    missing = False
    # This is weird now, but in the future we'll allow to inline multiple
    # packages
    for package in cfg.packages:
        if not is_package(package):
            sys.stderr.write(f"ERROR: {package} is not a python package")
            missing = True
    if missing:
        sys.exit(1)

    if cfg.default_package:
        if cfg.default_package not in cfg.packages:
            sys.stderr.write(f"ERROR: {cfg.default_pkg} is not a valid default package")
            sys.exit(2)
        # Convert the default package from path to package
        cfg.default_package = os.path.split(cfg.default_package)[1]


def main():
    cfg = parse_args()
    validate_args(cfg)
    process_files(cfg)


if __name__ == "__main__":
    main()
