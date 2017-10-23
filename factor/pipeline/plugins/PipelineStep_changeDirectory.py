import os
from lofarpipe.support.data_map import DataMap, DataProduct


def plugin_main(args, **kwargs):
    """
    Changes the directory of files in the input mapfile to new_dir

    Parameters
    ----------
    mapfile_in : str
        Name of the input mapfile to be expanded. (E.g. with the skymodels for the
        different groups.)
    new_dir : str
        Name of the local directory to sync to
    make_tempdir : bool
        Make temporary directory inside new_dir?
    append : str
        Append string to end of new files
    mapfile_dir : str
        Directory for output mapfile
    filename: str
        Name of output mapfile
    nitems_per_host: int
        Number of input items to give to a single host. This option can be used
        to ensure that a host has all the necessary files (they are assumed to
        be consecutive)

    Returns
    -------
    result : dict
        Output datamap filename

    """
    mapfile_in = kwargs['mapfile_in']
    new_dir = kwargs['new_dir']
    make_tempdir = True
    append = None
    if 'append' in kwargs:
        append =  kwargs['append']
    mapfile_dir = kwargs['mapfile_dir']
    filename = kwargs['filename']
    if 'nitems_per_host' in kwargs:
        nitems_per_host = int(float(kwargs['nitems_per_host']))
    else:
        nitems_per_host = 1

    map_in = DataMap.load(mapfile_in)
    map_out = DataMap([])
    map_in.iterator = DataMap.SkipIterator
    if nitems_per_host > 1:
        all_files = []
        for item in map_in:
            file_out = os.path.join(new_dir, os.path.basename(item.file))
            if append is not None:
                file_out += append
            all_files.append(file_out)
        file_groups = [all_files[i:i+nitems_per_host] for i  in range(0, len(all_files), nitems_per_host)]
        all_hosts = list(set([item.host for item in map_in]))
        numhosts = len(all_hosts)
        for i, file_list in enumerate(file_groups):
            host_out = all_hosts[i%numhosts]
            for file_out in file_list:
                map_out.data.append(DataProduct(host_out, file_out, False))
    else:
        for item in map_in:
            file_out = os.path.join(new_dir, os.path.basename(item.file))
            if append is not None:
                file_out += append
            map_out.data.append(DataProduct(item.host, file_out, False))

    fileid = os.path.join(mapfile_dir, filename)
    map_out.save(fileid)
    result = {'mapfile': fileid}

    return result


def string2bool(instring):
    if not isinstance(instring, basestring):
        raise ValueError('string2bool: Input is not a basic string!')
    if instring.upper() == 'TRUE' or instring == '1':
        return True
    elif instring.upper() == 'FALSE' or instring == '0':
        return False
    else:
        raise ValueError('string2bool: Cannot convert string "'+instring+'" to boolean!')


