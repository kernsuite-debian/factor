#! /usr/bin/env python
"""
Script to make a clean mask
"""
import argparse
from argparse import RawTextHelpFormatter
try:
    import bdsf
except ImportError:
    from lofar import bdsm as bdsf
import casacore.images as pim
from astropy.io import fits as pyfits
from astropy.coordinates import Angle
import pickle
import numpy as np
import sys
import os
from factor.lib.polygon import Polygon
from factor.scripts import blank_image


def read_vertices(filename, cal_only=False):
    """
    Returns facet vertices

    Parameters
    ----------
    filename : str
        Filename of pickled file with direction vertices

    """
    with open(filename, 'r') as f:
        direction_dict = pickle.load(f)
    if cal_only:
        return direction_dict['vertices_cal']
    else:
        return direction_dict['vertices']


def read_casa_polys(filename, image):
    """
    Reads casa region file and returns polys
    """
    with open(filename, 'r') as f:
        lines = f.readlines()

    polys = []
    for line in lines:
        if line.startswith('poly'):
            poly_str_temp = line.split('[[')[1]
            poly_str = poly_str_temp.split(']]')[0]
            poly_str_list = poly_str.split('], [')
            ra = []
            dec = []
            for pos in poly_str_list:
                RAstr, Decstr = pos.split(',')
                ra.append(Angle(RAstr, unit='hourangle').to('deg').value)
                dec.append(Angle(Decstr.replace('.', ':', 2), unit='deg').to('deg').value)
            poly_vertices = [np.array(ra), np.array(dec)]

            # Convert to image-plane polygon
            xvert = []
            yvert = []
            for RAvert, Decvert in zip(np.array(ra), np.array(dec)):
                try:
                    pixels = image.topixel([0, 1, Decvert*np.pi/180.0,
                                               RAvert*np.pi/180.0])
                except:
                    pixels = image.topixel([1, 1, Decvert*np.pi/180.0,
                                               RAvert*np.pi/180.0])
                # remove points that are too close to each other
                if len(xvert)>0:
                    dist = (xvert[-1]-pixels[2])**2 + (yvert[-1]-pixels[3])**2
                    if dist < .5:
                        continue
                xvert.append(pixels[2]) # x -> Dec
                yvert.append(pixels[3]) # y -> RA
            # check if first and last points are too close
            dist = (xvert[-1]-xvert[0])**2 + (yvert[-1]-yvert[0])**2
            if dist < .5:
                xvert.pop()
                yvert.pop()
            # check if segments intersect
            newpolygon = Polygon(xvert, yvert)
            if newpolygon.check_intersections() > 0:
                raise ValueError("Found intersections in manually defined polygon! Aborting.")
            polys.append(newpolygon)

        elif line.startswith('ellipse'):
            ell_str_temp = line.split('[[')[1]
            if '], 0.0' not in ell_str_temp and '], 90.0' not in ell_str_temp:
                print('Only position angles of 0.0 and 90.0 are supported for CASA '
                    'regions of type "ellipse"')
                sys.exit(1)
            if '], 0.0' in ell_str_temp:
                ell_str = ell_str_temp.split('], 0.0')[0]
                pa = 0
            else:
                ell_str = ell_str_temp.split('], 90.0')[0]
                pa = 90
            ell_str_list = ell_str.split('], [')

            # Ellipse center
            RAstr, Decstr = ell_str_list[0].split(',')
            ra_center = Angle(RAstr, unit='hourangle').to('deg').value
            dec_center = Angle(Decstr.replace('.', ':', 2), unit='deg').to('deg').value
            try:
                pixels = image.topixel([0, 1, dec_center*np.pi/180.0,
                    ra_center*np.pi/180.0])
            except:
                pixels = image.topixel([1, 1, dec_center*np.pi/180.0,
                    ra_center*np.pi/180.0])
            x_center = pixels[2] # x -> Dec
            y_center = pixels[3] # y -> RA

            # Ellipse semimajor and semiminor axes
            a_str, b_str = ell_str_list[1].split(',')
            a_deg = float(a_str.split('arcsec')[0])/3600.0
            b_deg = float(b_str.split('arcsec')[0])/3600.0
            try:
                pixels1 = image.topixel([0, 1, (dec_center-a_deg/2.0)*np.pi/180.0,
                    ra_center*np.pi/180.0])
            except:
                pixels1 = image.topixel([1, 1, (dec_center-a_deg/2.0)*np.pi/180.0,
                    ra_center*np.pi/180.0])
            a_pix1 = pixels1[2]
            try:
                pixels2 = image.topixel([0, 1, (dec_center+a_deg/2.0)*np.pi/180.0,
                    ra_center*np.pi/180.0])
            except:
                pixels2 = image.topixel([1, 1, (dec_center+a_deg/2.0)*np.pi/180.0,
                    ra_center*np.pi/180.0])
            a_pix2 = pixels2[2]
            a_pix = abs(a_pix2 - a_pix1)
            ex = []
            ey = []
            for th in range(0, 360, 1):
                if pa == 0:
                    # semimajor axis is along x-axis
                    ex.append(a_pix * np.cos(th * np.pi / 180.0)
                        + x_center) # x -> Dec
                    ey.append(a_pix * b_deg / a_deg * np.sin(th * np.pi / 180.0) + y_center) # y -> RA
                elif pa == 90:
                    # semimajor axis is along y-axis
                    ex.append(a_pix * b_deg / a_deg * np.cos(th * np.pi / 180.0)
                        + x_center) # x -> Dec
                    ey.append(a_pix * np.sin(th * np.pi / 180.0) + y_center) # y -> RA
            polys.append(Polygon(ex, ey))

        elif line.startswith('box'):
            poly_str_temp = line.split('[[')[1]
            poly_str = poly_str_temp.split(']]')[0]
            poly_str_list = poly_str.split('], [')
            ra = []
            dec = []
            for pos in poly_str_list:
                RAstr, Decstr = pos.split(',')
                ra.append(Angle(RAstr, unit='hourangle').to('deg').value)
                dec.append(Angle(Decstr.replace('.', ':', 2), unit='deg').to('deg').value)
            ra.insert(1, ra[0])
            dec.insert(1, dec[1])
            ra.append(ra[2])
            dec.append(dec[0])
            poly_vertices = [np.array(ra), np.array(dec)]

            # Convert to image-plane polygon
            xvert = []
            yvert = []
            for RAvert, Decvert in zip(np.array(ra), np.array(dec)):
                try:
                    pixels = image.topixel([0, 1, Decvert*np.pi/180.0,
                                               RAvert*np.pi/180.0])
                except:
                    pixels = image.topixel([1, 1, Decvert*np.pi/180.0,
                                               RAvert*np.pi/180.0])
                xvert.append(pixels[2]) # x -> Dec
                yvert.append(pixels[3]) # y -> RA
            polys.append(Polygon(xvert, yvert))

        elif line.startswith('#'):
            pass

        else:
            print('Only CASA regions of type "poly", "box", or "ellipse" are supported')
            sys.exit(1)

    return polys


def make_template_image(image_name, reference_ra_deg, reference_dec_deg,
    imsize=512, cellsize_deg=0.000417):
    """
    Make a blank image and save it to disk

    Parameters
    ----------
    image_name : str
        Filename of output image
    reference_ra_deg : float, optional
        RA for center of output mask image
    reference_dec_deg : float, optional
        Dec for center of output mask image
    imsize : int, optional
        Size of output image
    cellsize_deg : float, optional
        Size of a pixel in degrees

    """
    shape_out = [1, 1, imsize, imsize]
    hdu = pyfits.PrimaryHDU(np.zeros(shape_out, dtype=np.float32))
    hdulist = pyfits.HDUList([hdu])
    header = hdulist[0].header

    # Add WCS info
    header['CRVAL1'] = reference_ra_deg
    header['CDELT1'] = -cellsize_deg
    header['CRPIX1'] = imsize/2.0
    header['CUNIT1'] = 'deg'
    header['CTYPE1'] = 'RA---SIN'
    header['CRVAL2'] = reference_dec_deg
    header['CDELT2'] = cellsize_deg
    header['CRPIX2'] = imsize/2.0
    header['CUNIT2'] = 'deg'
    header['CTYPE2'] = 'DEC--SIN'

    # Add STOKES info
    header['CRVAL3'] = 1.0
    header['CDELT3'] = 1.0
    header['CRPIX3'] = 1.0
    header['CUNIT3'] = ''
    header['CTYPE3'] = 'STOKES'

    # Add frequency info
    header['RESTFRQ'] = 15036
    header['CRVAL4'] = 150e6
    header['CDELT4'] = 3e8
    header['CRPIX4'] = 1.0
    header['CUNIT4'] = 'HZ'
    header['CTYPE4'] = 'FREQ'
    header['SPECSYS'] = 'TOPOCENT'

    # Add equinox
    header['EQUINOX'] = 2000.0

    # Add telescope
    header['TELESCOP'] = 'LOFAR'

    hdulist[0].header = header

    hdulist.writeto(image_name, clobber=True)
    hdulist.close()


def vertices_to_poly(vertices, ref_im):
    """Converts a list of RA, Dec vertices to a Polygon object"""
    RAverts = vertices[0]
    Decverts = vertices[1]
    xvert = []
    yvert = []
    for RAvert, Decvert in zip(RAverts, Decverts):
        try:
            pixels = ref_im.topixel([0, 1, Decvert*np.pi/180.0,
                                       RAvert*np.pi/180.0])
        except:
            pixels = ref_im.topixel([1, 1, Decvert*np.pi/180.0,
                                       RAvert*np.pi/180.0])
        xvert.append(pixels[2]) # x -> Dec
        yvert.append(pixels[3]) # y -> RA

    return Polygon(xvert, yvert)


def main(image_name, mask_name, atrous_do=False, threshisl=0.0, threshpix=0.0, rmsbox=None,
         rmsbox_bright=(35, 7), iterate_threshold=False, adaptive_rmsbox=False, img_format='fits',
         threshold_format='float', trim_by=0.0, vertices_file=None, atrous_jmax=6,
         pad_to_size=None, skip_source_detection=False, region_file=None, nsig=1.0,
         reference_ra_deg=None, reference_dec_deg=None, cellsize_deg=0.000417,
         use_adaptive_threshold=False, make_blank_image=False, adaptive_thresh=150.0,
         exclude_cal_region=False, dilate=0):
    """
    Make a clean mask and return clean threshold

    Parameters
    ----------
    image_name : str
        Filename of input image from which mask will be made. If the image does
        not exist or make_blank_image is True, a template image with center at
        (reference_ra_deg, reference_dec_deg) will be made internally
    mask_name : str
        Filename of output mask image
    atrous_do : bool, optional
        Use wavelet module of PyBDSF?
    threshisl : float, optional
        Value of thresh_isl PyBDSF parameter
    threshpix : float, optional
        Value of thresh_pix PyBDSF parameter
    rmsbox : tuple of floats, optional
        Value of rms_box PyBDSF parameter
    rmsbox_bright : tuple of floats, optional
        Value of rms_box_bright PyBDSF parameter
    iterate_threshold : bool, optional
        If True, threshold will be lower in 20% steps until
        at least one island is found
    adaptive_rmsbox : tuple of floats, optional
        Value of adaptive_rms_box PyBDSF parameter
    img_format : str, optional
        Format of output mask image (one of 'fits' or 'casa')
    threshold_format : str, optional
        Format of output threshold (one of 'float' or 'str_with_units')
    trim_by : float, optional
        Fraction by which the perimeter of the output mask will be
        trimmed (zeroed)
    vertices_file : str, optional
        Filename of file with vertices (must be a pickle file containing
        a dictionary with the vertices in the 'vertices' entry)
    atrous_jmax : int, optional
        Value of atrous_jmax PyBDSF parameter
    pad_to_size : int, optional
        Pad output mask image to a size of pad_to_size x pad_to_size
    skip_source_detection : bool, optional
        If True, source detection is not run on the input image
    region_file : str, optional
        Filename of region file in CASA format to use as the mask. If update_user_mask
        is True, regions in region_file are unioned with ones found by the
        source finder
    nsig : float, optional
        Number of sigma of returned threshold value
    reference_ra_deg : float, optional
        RA for center of output mask image
    reference_dec_deg : float, optional
        Dec for center of output mask image
    cellsize_deg : float, optional
        Size of a pixel in degrees
    use_adaptive_threshold : bool, optional
        If True, use an adaptive threshold estimated from the negative values in
        the image
    make_blank_image : bool, optional
        If True, a blank template image is made. In this case, reference_ra_deg
        and reference_dec_deg must be specified
    adaptive_thresh : float, optional
        If adaptive_rmsbox is True, this value sets the threshold above
        which a source will use the small rms box
    exclude_cal_region : bool, optional
        If True, and a vertices_file is given, the calibrator region is also
        exclude from the output mask
    dilate : int, optional
        Number of dilation iterations for PyBDSF mask

    Returns
    -------
    result : dict
        Dict with nsig-sigma rms threshold

    """
    if rmsbox is not None and type(rmsbox) is str:
        rmsbox = eval(rmsbox)

    if type(rmsbox_bright) is str:
        rmsbox_bright = eval(rmsbox_bright)

    if pad_to_size is not None and type(pad_to_size) is str:
        pad_to_size = int(pad_to_size)

    if type(atrous_do) is str:
        if atrous_do.lower() == 'true':
            atrous_do = True
            threshisl = 4.0 # override user setting to ensure proper source fitting
        else:
            atrous_do = False

    if type(iterate_threshold) is str:
        if iterate_threshold.lower() == 'true':
            iterate_threshold = True
        else:
            iterate_threshold = False

    if type(adaptive_rmsbox) is str:
        if adaptive_rmsbox.lower() == 'true':
            adaptive_rmsbox = True
        else:
            adaptive_rmsbox = False

    if type(skip_source_detection) is str:
        if skip_source_detection.lower() == 'true':
            skip_source_detection = True
        else:
            skip_source_detection = False

    if type(use_adaptive_threshold) is str:
        if use_adaptive_threshold.lower() == 'true':
            use_adaptive_threshold = True
        else:
            use_adaptive_threshold = False

    if reference_ra_deg is not None and reference_dec_deg is not None:
        reference_ra_deg = float(reference_ra_deg)
        reference_dec_deg = float(reference_dec_deg)

    if type(make_blank_image) is str:
        if make_blank_image.lower() == 'true':
            make_blank_image = True
        else:
            make_blank_image = False
    if not os.path.exists(image_name):
        make_blank_image = True

    if type(exclude_cal_region) is str:
        if exclude_cal_region.lower() == 'true':
            exclude_cal_region = True
        else:
            exclude_cal_region = False

    dilate = int(dilate)

    if make_blank_image:
        print('Making empty template image...')
        if not skip_source_detection:
            print('ERROR: Source detection cannot be done on an empty image')
            sys.exit(1)
        if reference_ra_deg is not None and reference_dec_deg is not None:
            image_name = mask_name + '.tmp'
            make_template_image(image_name, reference_ra_deg, reference_dec_deg,
                cellsize_deg=float(cellsize_deg))
        else:
            print('ERROR: a reference position must be given to make an empty template image')
            sys.exit(1)

    trim_by = float(trim_by)
    atrous_jmax = int(atrous_jmax)
    threshpix = float(threshpix)
    threshisl = float(threshisl)
    nsig = float(nsig)
    adaptive_thresh = float(adaptive_thresh)
    threshold = 0.0
    nisl = 0

    if not skip_source_detection:
        if vertices_file is not None:
            # Modify the input image to blank the regions outside of the polygon
            blank_image.main(image_name, vertices_file, image_name+'.blanked',
                blank_value='nan')
            image_name += '.blanked'

        if use_adaptive_threshold:
            # Get an estimate of the rms
            img = bdsf.process_image(image_name, mean_map='zero', rms_box=rmsbox,
                                     thresh_pix=threshpix, thresh_isl=threshisl,
                                     atrous_do=atrous_do, thresh='hard',
                                     adaptive_rms_box=adaptive_rmsbox, adaptive_thresh=adaptive_thresh,
                                     rms_box_bright=rmsbox_bright, rms_map=True, quiet=True,
                                     atrous_jmax=atrous_jmax, stop_at='isl')

            # Find min and max pixels
            max_neg_val = abs(np.min(img.ch0_arr))
            max_neg_pos = np.where(img.ch0_arr == np.min(img.ch0_arr))
            max_pos_val = abs(np.max(img.ch0_arr))
            max_pos_pos = np.where(img.ch0_arr == np.max(img.ch0_arr))

            # Estimate new thresh_isl from min pixel value's sigma, but don't let
            # it get higher than 1/2 of the peak's sigma
            threshisl_neg = 2.0 * max_neg_val / img.rms_arr[max_neg_pos][0]
            max_sigma = max_pos_val / img.rms_arr[max_pos_pos][0]
            if threshisl_neg > max_sigma / 2.0:
                threshisl_neg = max_sigma / 2.0

            # Use the new threshold only if it is larger than the user-specified one
            if threshisl_neg > threshisl:
                threshisl = threshisl_neg

        if not atrous_do:
            stop_at = 'isl'
        else:
            stop_at = None
        if iterate_threshold:
            # Start with given threshold and lower it until we get at least one island
            nisl = 0
            while nisl == 0:
                img = bdsf.process_image(image_name, mean_map='zero', rms_box=rmsbox,
                                         thresh_pix=threshpix, thresh_isl=threshisl,
                                         atrous_do=atrous_do, thresh='hard',
                                         adaptive_rms_box=adaptive_rmsbox, adaptive_thresh=adaptive_thresh,
                                         rms_box_bright=rmsbox_bright, rms_map=True, quiet=True,
                                         atrous_jmax=atrous_jmax, stop_at=stop_at)
                nisl = img.nisl
                threshpix /= 1.2
                threshisl /= 1.2
                if threshpix < 5.0:
                    break
        else:
            img = bdsf.process_image(image_name, mean_map='zero', rms_box=rmsbox,
                                     thresh_pix=threshpix, thresh_isl=threshisl,
                                     atrous_do=atrous_do, thresh='hard',
                                     adaptive_rms_box=adaptive_rmsbox, adaptive_thresh=adaptive_thresh,
                                     rms_box_bright=rmsbox_bright, rms_map=True, quiet=True,
                                     atrous_jmax=atrous_jmax, stop_at=stop_at)
        nisl = img.nisl
        if nisl == 0:
            if region_file is None or region_file == '[]':
                print('No islands found. Clean mask cannot be made.')
                return {'threshold_5sig': 'None'}
            else:
                # Continue on and use user-supplied region file
                threshold = nsig * img.clipped_rms
        else:
            # Write out the mask
            img.export_image(img_type='island_mask', mask_dilation=dilate, outfile=mask_name,
                             img_format=img_format, clobber=True)

        # Check if there are large islands present (indicating that multi-scale
        # clean is needed)
        has_large_isl = False
        for isl in img.islands:
            if isl.size_active > 100:
                # Assuming normal sampling, a size of 100 pixels would imply
                # a source of ~ 10 beams
                has_large_isl = True

    if (vertices_file is not None or trim_by > 0 or pad_to_size is not None
        or (region_file is not None and region_file != '[]')
        or skip_source_detection):
        # Alter the mask in various ways
        if skip_source_detection or nisl == 0:
            # Read the image
            mask_im = pim.image(image_name)
        else:
            # Read the PyBDSF mask
            mask_im = pim.image(mask_name)
        data = mask_im.getdata()
        coordsys = mask_im.coordinates()
        if reference_ra_deg is not None and reference_dec_deg is not None:
            values = coordsys.get_referencevalue()
            values[2][0] = reference_dec_deg/180.0*np.pi
            values[2][1] = reference_ra_deg/180.0*np.pi
            coordsys.set_referencevalue(values)
        imshape = mask_im.shape()
        del(mask_im)

        if pad_to_size is not None:
            imsize = pad_to_size
            coordsys['direction'].set_referencepixel([imsize/2, imsize/2])
            pixmin = (imsize - imshape[2]) / 2
            if pixmin < 0:
                print("The padded size must be larger than the original size.")
                sys.exit(1)
            pixmax = pixmin + imshape[2]
            data_pad = np.zeros((1, 1, imsize, imsize), dtype=np.float32)
            data_pad[0, 0, pixmin:pixmax, pixmin:pixmax] = data[0, 0]
            new_mask = pim.image('', shape=(1, 1, imsize, imsize), coordsys=coordsys)
            new_mask.putdata(data_pad)
        else:
            new_mask = pim.image('', shape=imshape, coordsys=coordsys)
            new_mask.putdata(data)

        data = new_mask.getdata()

        if skip_source_detection or nisl == 0:
            if region_file is not None and region_file != '[]':
                # Unmask all pixels. We will fill the masked regions
                # below
                data[:] = 0
            else:
                # Mask all pixels
                data[:] = 1

        if region_file is not None and region_file != '[]':
            # Merge the CASA regions with the mask
            casa_polys = read_casa_polys(region_file.strip('[]"'), new_mask)
            for poly in casa_polys:
                # Find unmasked regions
                unmasked_ind = np.where(data[0, 0] == 0)

                # Find distance to nearest poly edge and mask those that
                # are inside the casa region (dist > 0)
                dist = poly.is_inside(unmasked_ind[0], unmasked_ind[1])
                inside_ind = np.where(dist > 0.0)
                if len(inside_ind[0]) > 0:
                    data[0, 0, unmasked_ind[0][inside_ind], unmasked_ind[1][inside_ind]] = 1

        if vertices_file is not None:
            # Modify the clean mask to exclude regions outside of the polygon
            vertices = read_vertices(vertices_file)
            poly = vertices_to_poly(vertices, new_mask)
            if exclude_cal_region:
                cal_vertices = read_vertices(vertices_file, cal_only=True)
                cal_poly = vertices_to_poly(cal_vertices, new_mask)

            # Find masked regions
            masked_ind = np.where(data[0, 0])

            # Find distance to nearest poly edge and unmask those that
            # are outside the facet (dist < 0) and inside the calibrator region
            # (cal_dist > 0)
            dist = poly.is_inside(masked_ind[0], masked_ind[1])
            outside_ind = np.where(dist < 0.0)
            if len(outside_ind[0]) > 0:
                data[0, 0, masked_ind[0][outside_ind], masked_ind[1][outside_ind]] = 0
            if exclude_cal_region:
                masked_ind = np.where(data[0, 0])
                cal_dist = cal_poly.is_inside(masked_ind[0], masked_ind[1])
                inside_ind = np.where(cal_dist > 0.0)
                if len(inside_ind[0]) > 0:
                    data[0, 0, masked_ind[0][inside_ind], masked_ind[1][inside_ind]] = 0

        if trim_by > 0.0:
            sh = np.shape(data)
            margin = int(sh[2] * trim_by / 2.0 )
            data[0, 0, 0:sh[2], 0:margin] = 0
            data[0, 0, 0:margin, 0:sh[3]] = 0
            data[0, 0, 0:sh[2], sh[3]-margin:sh[3]] = 0
            data[0, 0, sh[2]-margin:sh[2], 0:sh[3]] = 0

        # Save changes
        new_mask.putdata(data)
        if img_format == 'fits':
            new_mask.tofits(mask_name, overwrite=True)
        elif img_format == 'casa':
            new_mask.saveas(mask_name, overwrite=True)
        else:
            print('Output image format "{}" not understood.'.format(img_format))
            sys.exit(1)

    if not skip_source_detection:
        if threshold_format == 'float':
            return {'threshold_5sig': nsig * img.clipped_rms, 'multiscale': has_large_isl}
        elif threshold_format == 'str_with_units':
            # This is done to get around the need for quotes around strings in casapy scripts
            # 'casastr/' is removed by the generic pipeline
            return {'threshold_5sig': 'casastr/{0}Jy'.format(nsig * img.clipped_rms),
                'multiscale': has_large_isl}
    else:
        return {'threshold_5sig': '0.0'}


if __name__ == '__main__':
    descriptiontext = "Make a clean mask.\n"

    parser = argparse.ArgumentParser(description=descriptiontext, formatter_class=RawTextHelpFormatter)
    parser.add_argument('image_name', help='Image name')
    parser.add_argument('mask_name', help='Mask name')
    parser.add_argument('-a', '--atrous_do', help='use wavelet fitting', type=bool, default=False)
    parser.add_argument('-i', '--threshisl', help='', type=float, default=3.0)
    parser.add_argument('-p', '--threshpix', help='', type=float, default=5.0)
    parser.add_argument('-r', '--rmsbox', help='rms box width and step (e.g., "(60, 20)")',
        type=str, default='(60, 20)')
    parser.add_argument('--rmsbox_bright', help='rms box for bright sources(?) width and step (e.g., "(60, 20)")',
        type=str, default='(60, 20)')
    parser.add_argument('-t', '--iterate_threshold', help='iteratively decrease threshold until at least '
        'one island is found', type=bool, default=False)
    parser.add_argument('-o', '--adaptive_rmsbox', help='use an adaptive rms box', type=bool, default=False)
    parser.add_argument('-f', '--img_format', help='format of output mask', type=str, default='casa')
    parser.add_argument('-d', '--threshold_format', help='format of return value', type=str, default='float')
    parser.add_argument('-b', '--trim_by', help='Trim masked region by this number of pixels', type=float, default=0.0)
    parser.add_argument('-v', '--vertices_file', help='file containing facet polygon vertices', type=str, default=None)
    parser.add_argument('--region_file', help='File containing casa regions to be merged with the detected mask', type=str, default=None)
    parser.add_argument('-j', '--atrous_jmax', help='Max wavelet scale', type=int, default=3)
    parser.add_argument('-z', '--pad_to_size', help='pad mask to this size', type=int, default=None)
    parser.add_argument('-s', '--skip_source_detection', help='skip source detection', type=bool, default=False)

    args = parser.parse_args()
    erg = main(args.image_name, args.mask_name, atrous_do=args.atrous_do,
               threshisl=args.threshisl, threshpix=args.threshpix, rmsbox=args.rmsbox,
               rmsbox_bright=args.rmsbox_bright,
               iterate_threshold=args.iterate_threshold,
               adaptive_rmsbox=args.adaptive_rmsbox, img_format=args.img_format,
               threshold_format=args.threshold_format, trim_by=args.trim_by,
               vertices_file=args.vertices_file, atrous_jmax=args.atrous_jmax,
               pad_to_size=args.pad_to_size, skip_source_detection=args.skip_source_detection,
               region_file=args.region_file)
    print erg
