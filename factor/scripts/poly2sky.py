#! /usr/bin/env python
"""
Script to make a normal sky model from a polynomial sky model
"""
import argparse
from argparse import RawTextHelpFormatter
from astropy.io import fits
from astropy import wcs
import numpy as np
from numpy.polynomial.polynomial import polyval
import casacore.tables as pt
import lsmtool
import re
import sys
import os
import glob


def main(model_root, ms_file, skymodel, fits_mask=None, min_peak_flux_jy=0.0001,
    max_residual_jy=0.0):
    """
    Make a makesourcedb sky model for input MS from WSClean fits model images

    Parameters
    ----------
    model_root : str
        Root name of WSClean polynomial model sky model
    ms_file : str
        Filename of MS for which sky model is to be made. Can be a list of files
        (e.g., '[ms1,ms2,...]', in which case they should all have the same
        frequency
    skymodel : str
        Filename of the output makesourcedb sky model
    fits_mask : str, optional
        Filename of fits mask
    min_peak_flux_jy : float, optional
        Minimum absolute value of flux in Jy of a source in lowest-frequency model image
        to include in output model
    max_residual_jy : float, optional
        Maximum acceptible total residual absolute flux in Jy

    """
    min_peak_flux_jy = float(min_peak_flux_jy)
    max_residual_jy = float(max_residual_jy)

    if type(fits_mask) is str:
        if fits_mask.lower() == 'none':
            fits_mask = None

    # Read MS file and get the frequency info
    if '[' in ms_file and ']' in ms_file:
        files = ms_file.strip('[]').split(',')
        files = [f.strip() for f in files]
        ms_file = files[0]
    sw = pt.table(ms_file+'::SPECTRAL_WINDOW', ack=False)
    ms_freq = sw.col('REF_FREQUENCY')[0]
    sw.close()

    # Read in sky model
    polymodel = model_root + '-sources.txt'
    s = lsmtool.load(polymodel)
    ref_freq = float(s.getColValues('ReferenceFrequency')[0]) # Hz

    # Find model images and read in frequencies
    fits_models = glob.glob(model_root+'-00*-model.fits')
    if len(fits_models) == 0:
        # No channels images found, so look for non-MFS images
        fits_models = glob.glob(model_root+'-model.fits')
    if len(fits_models) == 0:
        print('ERROR: no model images found')
        sys.exit(1)
    freqs = []
    for f in fits_models:
        # Get the frequency info
        hdr = fits.getheader(f, 0, ignore_missing_end=True)
        freqs.append(hdr['CRVAL3']) # Hz

    # Determine nearest model frequency to MS frequency. We will use this to
    # get the fluxes (to match the frequency blocks used during imaging and
    # calibration)
    sky_freq = min(freqs, key=lambda x:abs(x-ms_freq))

    # Check if fits mask is empty
    if fits_mask is not None:
        if fits_mask.lower() == 'empty':
            # Handle case in which no sources were found during masking
            s.remove(np.array(range(len(s))))
            mask = None
        else:
            mask = fits.getdata(fits_mask, 0, ignore_missing_end=True)
            hdr = fits.getheader(fits_mask, 0, ignore_missing_end=True)
            w = wcs.WCS(hdr)
    else:
        mask = None

    # Discard components not in the mask, if given
    if mask is not None:
        pix = w.wcs_world2pix(np.array([s.getColValues('RA'), s.getColValues('Dec'),
            [0]*len(s), [0]*len(s)]).T, 0)
        not_in_mask = []
        for i, p in enumerate(pix):
            if mask[0, 0, int(round(p[1])), int(round(p[0]))] < 1:
                not_in_mask.append(i)
        s.remove(np.array(not_in_mask))

    # Set fluxes and ref frequency
    specterms = s.getColValues('SpectralIndex')
    stokesI = s.getColValues('I')
    fluxes = []
    for i in range(len(s)):
        # Find flux as follows:
        #     flux(nu) = stokesI + term0 (nu/refnu - 1) + term1 (nu/refnu - 1)^2 + ...,
        # where nu = sky_freq and refnu = ref_freq
        polyterms = specterms[i].tolist()
        polyterms.insert(0, stokesI[i])
        fluxes.append(polyval(sky_freq/ref_freq-1.0, polyterms))
    s.setColValues('I', fluxes)
    s.setColValues('ReferenceFrequency', [ms_freq]*len(s))

    # Remove spectral index values
    s.table.remove_column('SpectralIndex')
    s.table.remove_column('LogarithmicSI')

    # Write the new sky model
    s.write(fileName=skymodel, clobber=True)


if __name__ == '__main__':
    descriptiontext = "Make a makesourcedb sky model from WSClean fits model images.\n"

    parser = argparse.ArgumentParser(description=descriptiontext, formatter_class=RawTextHelpFormatter)
    parser.add_argument('fits_model_root', help='Root of model images')
    parser.add_argument('ms_file', help='Filename of MS for which sky model is to be made')
    parser.add_argument('skymodel', help='Filename of output sky model')
    parser.add_argument('-f' '--fits_mask', help='Filename of fits mask', type=str, default=None)
    parser.add_argument('-p', '--min_peak_flux_jy', help='Minimum absolute value of flux in Jy', type=float, default=0.0001)
    parser.add_argument('-r', '--max_residual_jy', help='Maximum acceptible total residual absolute flux in Jy', type=float, default=0.0)
    parser.add_argument('-i', '--interp', help='Interpolation method', type=str, default='linear')
    args = parser.parse_args()
    main(args.fits_model_root, args.ms_file, args.skymodel, fits_mask=args.fits_mask,
        min_peak_flux_jy=args.min_peak_flux_jy, max_residual_jy=args.max_residual_jy,
        interp=args.interp)
