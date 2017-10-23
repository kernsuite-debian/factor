#!/usr/bin/env python
"""
Script to verify selfcal subtract
"""
import argparse
from argparse import RawTextHelpFormatter
import numpy
import casacore.images as pim
import os


def main(image_pre, image_post, res_val, max_factor=0.25):
    """
    Verify subtraction by checking quantities in residual images

    Parameters
    ----------
    image_pre : str
        Filename of image before selfcal
    image_post : str
        Filename of image after selfcal
    res_val : float
        Maximum allowed value of peak residual (Jy/beam)
    max_factor : float
        Factor by which old peak residual must exceed new peak residual

    """
    imgpre = pim.image(image_pre)
    maxvalpre = numpy.max(numpy.abs(imgpre.getdata()))
    imgpost = pim.image(image_post)
    maxvalpost = numpy.max(numpy.abs(imgpost.getdata()))

    if (maxvalpost > res_val) or (maxvalpost*max_factor > maxvalpre):
        return {'break': False, 'maxvalpost': maxvalpost, 'maxvalpre': maxvalpre}
    else:
        return {'break': True, 'maxvalpost': maxvalpost, 'maxvalpre': maxvalpre}


if __name__ == '__main__':
    descriptiontext = "Check residual images.\n"

    parser = argparse.ArgumentParser(description=descriptiontext, formatter_class=RawTextHelpFormatter)
    parser.add_argument('image_pre', help='image before selfcal')
    parser.add_argument('image_post', help='image after selfcal')
    parser.add_argument('res_val', help='maximum acceptible residual in Jy')
    parser.add_argument('max_factor', help='factor by which old peak must exceed new one')

    args = parser.parse_args()
    main(args.image_pre, args.image_post, args.res_val, args.max_factor)
