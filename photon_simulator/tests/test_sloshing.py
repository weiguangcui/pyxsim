"""
Answer test the photon_simulator analysis module.
"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from photon_simulator import \
    TableApecModel, TableAbsorbModel, \
    ThermalSourceModel, PhotonList, EventList, \
    merge_files
from yt.config import ytcfg
from yt.testing import requires_file
from yt.utilities.answer_testing.framework import requires_ds, \
    GenericArrayTest, data_dir_load
from numpy.testing import assert_array_equal
from numpy.random import RandomState
from yt.units.yt_array import uconcatenate
import os
import tempfile
import shutil

def setup():
    from yt.config import ytcfg
    ytcfg["yt", "__withintesting"] = "True"

test_data_dir = ytcfg.get("yt", "test_data_dir")
xray_data_dir = ytcfg.get("yt", "xray_data_dir")

rmfs = ["pn-med.rmf", "acisi_aimpt_cy17.rmf",
        "aciss_aimpt_cy17.rmf", "nustar.rmf",
        "ah_sxs_5ev_basefilt_20100712.rmf"]
arfs = ["pn-med.arf", "acisi_aimpt_cy17.arf",
        "aciss_aimpt_cy17.arf", "nustar_3arcminA.arf",
        "sxt-s_120210_ts02um_intallpxl.arf"]

gslr = "GasSloshingLowRes/sloshing_low_res_hdf5_plt_cnt_0300"
APEC = xray_data_dir
TBABS = os.path.join(xray_data_dir, "tbabs_table.h5")

def return_data(data):
    def _return_data(name):
        return data
    return _return_data

@requires_ds(gslr)
@requires_file(APEC)
@requires_file(TBABS)
def test_sloshing():

    tmpdir = tempfile.mkdtemp()
    curdir = os.getcwd()
    os.chdir(tmpdir)

    prng = RandomState(0x4d3d3d3)

    ds = data_dir_load(gslr)
    A = 2000.
    exp_time = 1.0e4
    redshift = 0.1

    apec_model = TableApecModel(APEC, 0.1, 11.0, 10000)
    tbabs_model = TableAbsorbModel(TBABS, 0.1)

    sphere = ds.sphere("c", (0.1, "Mpc"))
    sphere.set_field_parameter("X_H", 0.75)

    thermal_model = ThermalSourceModel(apec_model, Zmet=0.3, prng=prng)
    photons1 = PhotonList.from_data_source(sphere, redshift, A, exp_time,
                                           thermal_model)

    return_photons = return_data(photons1.photons)

    tests = [GenericArrayTest(ds, return_photons, args=["photons"])]

    for a, r in zip(arfs, rmfs):
        arf = os.path.join(xray_data_dir, a)
        rmf = os.path.join(xray_data_dir, r)
        events1 = photons1.project_photons([1.0,-0.5,0.2], responses=[arf,rmf],
                                           absorb_model=tbabs_model,
                                           convolve_energies=True, prng=prng)

        events1["xsky"]
        return_events = return_data(events1.events)

        tests.append(GenericArrayTest(ds, return_events, args=[a]))

    for test in tests:
        test_sloshing.__name__ = test.description
        yield test

    photons1.write_h5_file("test_photons.h5")
    events1.write_h5_file("test_events.h5")

    photons2 = PhotonList.from_file("test_photons.h5")
    events2 = EventList.from_h5_file("test_events.h5")

    for k in photons1.keys():
        if k == "Energy":
            arr1 = uconcatenate(photons1[k])
            arr2 = uconcatenate(photons2[k])
        else:
            arr1 = photons1[k]
            arr2 = photons2[k]
        yield assert_array_equal, arr1, arr2
    for k in events1.keys():
        yield assert_array_equal, events1[k], events2[k]

    nevents = 0

    for i in range(4):
        events = photons1.project_photons([1.0,-0.5,0.2],
                                          exp_time_new=0.25*exp_time,
                                          absorb_model=tbabs_model,
                                          prng=prng)
        events.write_h5_file("split_events_%d.h5" % i)
        nevents += len(events["xsky"])

    merge_files(["split_events_%d.h5" % i for i in range(4)],
                "merged_events.h5", add_exposure_times=True,
                clobber=True)

    merged_events = EventList.from_h5_file("merged_events.h5")
    assert len(merged_events["xsky"]) == nevents
    assert merged_events.parameters["ExposureTime"] == exp_time

    os.chdir(curdir)
    shutil.rmtree(tmpdir)
