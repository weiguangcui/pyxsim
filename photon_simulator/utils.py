import numpy as np
from yt.funcs import iterable
from yt.units.yt_array import YTQuantity
from six import string_types
from collections import defaultdict
import h5py
import os

def force_unicode(value):
    if hasattr(value, 'decode'):
        return value.decode('utf8')
    else:
        return value

def parse_value(value, default_units):
    if isinstance(value, YTQuantity):
        return value.in_units(default_units)
    elif iterable(value):
        return YTQuantity(value[0], value[1]).in_units(default_units)
    else:
        return YTQuantity(value, default_units)

def validate_parameters(first, second, skip=[]):
    keys1 = list(first.keys())
    keys2 = list(first.keys())
    keys1.sort()
    keys2.sort()
    if keys1 != keys2:
        raise RuntimeError("The two inputs do not have the same parameters!")
    for k1, k2 in zip(keys1, keys2):
        if k1 not in skip:
            v1 = first[k1]
            v2 = second[k2]
            if isinstance(v1, string_types) or isinstance(v2, string_types):
                check_equal = v1 == v2
            else:
                check_equal = np.allclose(v1, v2, rtol=0.0, atol=1.0e-10)
            if not check_equal:
                raise RuntimeError("The values for the parameter '%s' in the two inputs" % k1 +
                                   " are not identical (%s vs. %s)!" % (v1, v2))

def merge_files(input_files, output_file, clobber=False,
                add_exposure_times=False):
    r"""
    Helper function for merging PhotonList or EventList HDF5 files.

    Parameters
    ----------
    input_files : list of strings
        List of filenames that will be merged together.
    output_file : string
        Name of the merged file to be outputted.
    clobber : boolean, default False
        If a the output file already exists, set this to True to
        overwrite it.
    add_exposure_times : boolean, default False
        If set to True, exposure times will be added together. Otherwise,
        the exposure times of all of the files must be the same.

    Examples
    --------
    >>> from yt.analysis_modules.photon_simulator.api import merge_files
    >>> merge_files(["events_0.h5","events_1.h5","events_3.h5"], "events.h5",
    ...             clobber=True, add_exposure_times=True)

    Notes
    -----
    Currently, to merge files it is mandated that all of the parameters have the
    same values, with the possible exception of the exposure time parameter "exp_time"
    if add_exposure_times=False.
    """
    if os.path.exists(output_file) and not clobber:
        raise IOError("Cannot overwrite existing file %s. " % output_file +
                      "If you want to do this, set clobber=True.")

    f_in = h5py.File(input_files[0], "r")
    f_out = h5py.File(output_file, "w")

    exp_time_key = ""
    p_out = f_out.create_group("parameters")
    for key, param in f_in["parameters"].items():
        if key.endswith("exp_time"):
            exp_time_key = key
        else:
            p_out[key] = param.value

    skip = [exp_time_key] if add_exposure_times else []
    for fn in input_files[1:]:
        f = h5py.File(fn, "r")
        validate_parameters(f_in["parameters"], f["parameters"], skip=skip)
        f.close()

    f_in.close()

    data = defaultdict(list)
    tot_exp_time = 0.0

    for i, fn in enumerate(input_files):
        f = h5py.File(fn, "r")
        if add_exposure_times:
            tot_exp_time += f["/parameters"][exp_time_key].value
        elif i == 0:
            tot_exp_time = f["/parameters"][exp_time_key].value
        for key in f["/data"]:
            data[key].append(f["/data"][key][:])
        f.close()

    p_out["exp_time"] = tot_exp_time

    d = f_out.create_group("data")
    for k in data:
        d.create_dataset(k, data=np.concatenate(data[k]))

    f_out.close()