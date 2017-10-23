import os
import glob
from lofarpipe.support.data_map import DataMap, DataProduct


def plugin_main(args, **kwargs):
    """
    Makes a mapfile for selfcal images (assuming standard naming conventions)

    Parameters
    ----------
    selfcal_dir : str
        Full path of selfcal directory
    hosts : list or str
        List of hosts/nodes. May be given as a list or as a string (e.g.,
        '[host1, host2]'
    mapfile_dir : str
        Directory for output mapfile
    filename: str
        Name of output mapfile

    Returns
    -------
    result : dict
        Output datamap filename

    """
    selfcal_dir = kwargs['selfcal_dir']
    if type(kwargs['hosts']) is str:
        hosts = kwargs['hosts'].strip('[]').split(',')
        hosts = [h.strip() for h in hosts]
    mapfile_dir = kwargs['mapfile_dir']
    filename = kwargs['filename']

    if os.path.exists(selfcal_dir):
        selfcal_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[01]2-MFS-image.fits'))
        tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22_iter*-MFS-image.fits'))
        if len(tec_iter_images) == 0:
            tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22-MFS-image.fits'))
        selfcal_images += tec_iter_images
        selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[3]2-MFS-image.fits'))
        selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image42_iter*-MFS-image.fits'))
        if len(selfcal_images) == 0:
            selfcal_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[01]2-image.fits'))
            tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22_iter*-image.fits'))
            if len(tec_iter_images) == 0:
                tec_iter_images = glob.glob(os.path.join(selfcal_dir, '*.wsclean_image22-image.fits'))
            selfcal_images += tec_iter_images
            selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image[3]2-image.fits'))
            selfcal_images += glob.glob(os.path.join(selfcal_dir, '*.wsclean_image42_iter*-image.fits'))
        selfcal_images.sort()
    else:
        selfcal_images = []

    # Save image list as a string to the output mapfile
    image_list = '[{0}]'.format(','.join(selfcal_images))
    map_out = DataMap([])
    map_out.data.append(DataProduct(hosts[0], image_list, False))

    fileid = os.path.join(mapfile_dir, filename)
    map_out.save(fileid)
    result = {'mapfile': fileid}

    return result
