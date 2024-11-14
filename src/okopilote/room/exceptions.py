# -*- coding: utf-8 -*-


class NoAvailableData(Exception):
    """No or not not enough input data to compute a result."""


class NoReliableData(Exception):
    """Data are not reliable to answer a request."""
