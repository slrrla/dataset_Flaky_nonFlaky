# -*- coding: utf-8 -*-
# Copyright 2017, IBM.
#
# This source code is licensed under the Apache License, Version 2.0 found in
# the LICENSE.txt file in the root directory of this source tree.

# pylint: disable=too-many-ancestors

"""Common utilities for QISKit."""

import logging
import re
import sys
import platform
import warnings
import socket
import psutil

logger = logging.getLogger(__name__)

FIRST_CAP_RE = re.compile('(.)([A-Z][a-z]+)')
ALL_CAP_RE = re.compile('([a-z0-9])([A-Z])')


def _check_python_version():
    """Check for Python version 3.5+
    """
    if sys.version_info < (3, 5):
        raise Exception('QISKit requires Python version 3.5 or greater.')


def _enable_deprecation_warnings():
    """
    Force the `DeprecationWarning` warnings to be displayed for the qiskit
    module, overriding the system configuration as they are ignored by default
    [1] for end-users.

    TODO: on Python 3.7, this might not be needed due to PEP-0565 [2].

    [1] https://docs.python.org/3/library/warnings.html#default-warning-filters
    [2] https://www.python.org/dev/peps/pep-0565/
    """
    # pylint: disable=invalid-name
    deprecation_filter = ('always', None, DeprecationWarning,
                          re.compile(r'^qiskit\.*', re.UNICODE), 0)

    # Instead of using warnings.simple_filter() directly, the internal
    # _add_filter() function is used for being able to match against the
    # module.
    try:
        warnings._add_filter(*deprecation_filter, append=False)
    except AttributeError:
        # ._add_filter is internal and not available in some Python versions.
        pass


def _camel_case_to_snake_case(identifier):
    """Return a `snake_case` string from a `camelCase` string.

    Args:
        identifier (str): a `camelCase` string.

    Returns:
        str: a `snake_case` string.
    """
    string_1 = FIRST_CAP_RE.sub(r'\1_\2', identifier)
    return ALL_CAP_RE.sub(r'\1_\2', string_1).lower()


_check_python_version()
_enable_deprecation_warnings()


def local_hardware_info():
    """Basic hardware information about the local machine.

    Gives actual number of CPU's in the machine, even when hyperthreading is
    turned on.

    Returns:
        dict: The hardware information.

    """
    results = {'os': platform.system()}
    results['memory'] = psutil.virtual_memory().total / (1024**3)
    results['cpus'] = psutil.cpu_count(logical=False)
    return results


def _has_connection(hostname, port):
    """Checks to see if internet connection exists to host
    via specified port

    Args:
        hostname (str): Hostname to connect to.
        port (int): Port to connect to

    Returns:
        bool: Has connection or not

    Raises:
        gaierror: No connection established.
    """
    try:
        host = socket.gethostbyname(hostname)
        socket.create_connection((host, port), 2)
        return True
    except socket.gaierror:
        pass
    return False
