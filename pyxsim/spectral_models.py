"""
Photon emission and absoprtion models.
"""
import numpy as np
import h5py

from soxs.spectra import ApecGenerator, get_wabs_absorb
from soxs.constants import cosmic_elem, metal_elem
from pyxsim.utils import mylog, check_file_location
from yt.units.yt_array import YTArray, YTQuantity
from yt.utilities.physical_constants import hcgs, clight

hc = (hcgs*clight).in_units("keV*angstrom").v
# NOTE: XSPEC has hc = 12.39854 keV*A, so there may be slight differences in
# placement of spectral lines due to the above
cl = clight.v

class XSpecThermalModel(object):
    r"""
    Initialize a thermal gas emission model from PyXspec.

    Parameters
    ----------
    model_name : string
        The name of the thermal emission model.
    emin : float
        The minimum energy for the spectral model.
    emax : float
        The maximum energy for the spectral model.
    nchan : integer
        The number of channels in the spectral model.
    thermal_broad : boolean, optional
        Whether or not the spectral lines should be thermally
        broadened.
    settings : dictionary, optional
        A dictionary of key, value pairs (must both be strings)
        that can be used to set various options in XSPEC.

    Examples
    --------
    >>> mekal_model = XSpecThermalModel("mekal", 0.05, 50.0, 1000)
    """
    def __init__(self, model_name, emin, emax, nchan,
                 thermal_broad=False, settings=None):
        mylog.warning("XSpecThermalModel is deprecated and will be removed "
                      "in a future release. Use of TableApecModel is suggested.")
        self.model_name = model_name
        self.thermal_broad = thermal_broad
        if settings is None: settings = {}
        self.settings = settings
        self.emin = emin
        self.emax = emax
        self.nchan = nchan
        self.ebins = np.linspace(self.emin, self.emax, nchan+1)
        self.de = np.diff(self.ebins)
        self.emid = 0.5*(self.ebins[1:]+self.ebins[:-1])

    def prepare_spectrum(self, zobs):
        """
        Prepare the thermal model for execution given a redshift *zobs* for the spectrum.
        """
        import xspec
        xspec.Xset.chatter = 0
        if self.thermal_broad:
            xspec.Xset.addModelString("APECTHERMAL","yes")
        for k,v in self.settings.items():
            xspec.Xset.addModelString(k,v)
        xspec.AllModels.setEnergies("%f %f %d lin" %
                                    (self.emin.value, self.emax.value, self.nchan))
        self.model = xspec.Model(self.model_name)
        self.thermal_comp = getattr(self.model, self.model_name)
        if self.model_name == "bremss":
            self.norm = 3.02e-15
        else:
            self.norm = 1.0e-14
        self.thermal_comp.norm = 1.0
        self.thermal_comp.Redshift = zobs

    def get_spectrum(self, kT):
        """
        Get the thermal emission spectrum given a temperature *kT* in keV. 
        """
        self.thermal_comp.kT = kT
        self.thermal_comp.Abundanc = 0.0
        cosmic_spec = np.array(self.model.values(0))
        if self.model_name == "bremss":
            metal_spec = np.zeros(self.nchan)
        else:
            self.thermal_comp.Abundanc = 1.0
            metal_spec = np.array(self.model.values(0)) - cosmic_spec
        cosmic_spec *= self.norm
        metal_spec *= self.norm
        return YTArray(cosmic_spec, "cm**3/s"), YTArray(metal_spec, "cm**3/s")

    def cleanup_spectrum(self):
        del self.thermal_comp
        del self.model

class TableApecModel(ApecGenerator):
    r"""
    Initialize a thermal gas emission model from the AtomDB APEC tables
    available at http://www.atomdb.org. This code borrows heavily from Python
    routines used to read the APEC tables developed by Adam Foster at the
    CfA (afoster@cfa.harvard.edu).

    Parameters
    ----------
    emin : float
        The minimum energy for the spectral model.
    emax : float
        The maximum energy for the spectral model.
    nchan : integer
        The number of channels in the spectral model.
    apec_root : string
        The directory root where the APEC model files are stored. If 
        not provided, the default is to look for them in the pyxsim
        "spectral_files" directory.
    apec_vers : string, optional
        The version identifier string for the APEC files, e.g.
        "2.0.2"
    thermal_broad : boolean, optional
        Whether or not the spectral lines should be thermally
        broadened.

    Examples
    --------
    >>> apec_model = TableApecModel(0.05, 50.0, 1000, apec_vers="3.0.3",
    ...                             thermal_broad=True)
    """
    def __init__(self, emin, emax, nchan, apec_root=None,
                 apec_vers="2.0.2", thermal_broad=False):
        super(TableApecModel, self).__init__(emin, emax, nchan, apec_root=apec_root,
                                             apec_vers=apec_vers, broadening=thermal_broad)
        self.nchan = self.nbins

    def prepare_spectrum(self, zobs):
        """
        Prepare the thermal model for execution given a redshift *zobs* for the spectrum.
        """
        cosmic_spec, metal_spec = self._get_table(list(range(self.nT)), zobs, 0.0)
        self.cosmic_spec = YTArray(cosmic_spec, "cm**3/s")
        self.metal_spec = YTArray(metal_spec, "cm**3/s")

    def get_spectrum(self, kT):
        """
        Get the thermal emission spectrum given a temperature *kT* in keV. 
        """
        tindex = np.searchsorted(self.Tvals, kT)-1
        if tindex >= self.Tvals.shape[0]-1 or tindex < 0:
            return (YTArray(np.zeros(self.nchan), "cm**3/s"),)*2
        dT = (kT-self.Tvals[tindex])/self.dTvals[tindex]
        cspec_l = self.cosmic_spec[tindex,:]
        mspec_l = self.metal_spec[tindex,:]
        cspec_r = self.cosmic_spec[tindex+1,:]
        mspec_r = self.metal_spec[tindex+1,:]
        cosmic_spec = cspec_l*(1.-dT)+cspec_r*dT
        metal_spec = mspec_l*(1.-dT)+mspec_r*dT
        return cosmic_spec, metal_spec

    def return_spectrum(self, temperature, metallicity, redshift, norm, velocity=0.0):
        """
        Given the properties of a thermal plasma, return a spectrum.

        Parameters
        ----------
        temperature : float
            The temperature of the plasma in keV.
        metallicity : float
            The metallicity of the plasma in solar units.
        redshift : float
            The redshift of the plasma.
        norm : float
            The normalization of the model, in the standard Xspec units of
            1.0e-14*EM/(4*pi*(1+z)**2*D_A**2).
        velocity : float, optional
            Velocity broadening parameter in km/s. Default: 0.0
        """
        spec = super(TableApecModel, self).get_spectrum(temperature, metallicity, redshift, norm,
                                                        velocity=velocity)
        return YTArray(spec.flux*spec.de, "photons/s/cm**2")

    def cleanup_spectrum(self):
        pass

class AbsorptionModel(object):
    def __init__(self, nH, emid, sigma):
        self.nH = YTQuantity(nH*1.0e22, "cm**-2")
        self.emid = YTArray(emid, "keV")
        self.sigma = YTArray(sigma, "cm**2")

    def prepare_spectrum(self):
        pass

    def get_absorb(self, e):
        """
        Get the absorption spectrum.
        """
        sigma = np.interp(e, self.emid, self.sigma, left=0.0, right=0.0)
        return np.exp(-sigma*self.nH)

    def cleanup_spectrum(self):
        pass

    def absorb_photons(self, eobs, prng=np.random):
        r"""
        Determine which photons will be absorbed by foreground
        galactic absorption.

        Parameters
        ----------
        eobs : array_like
            The energies of the photons in keV.
        prng : :class:`~numpy.random.RandomState` object or :mod:`~numpy.random`, optional
            A pseudo-random number generator. Typically will only be specified
            if you have a reason to generate the same set of random numbers, such as for a
            test. Default is the :mod:`numpy.random` module.
        """
        mylog.info("Absorbing.")
        self.prepare_spectrum()
        absorb = self.get_absorb(eobs)
        randvec = prng.uniform(size=eobs.shape)
        detected = randvec < absorb
        self.cleanup_spectrum()
        return detected

class XSpecAbsorbModel(AbsorptionModel):
    r"""
    Initialize an absorption model from PyXspec.

    Parameters
    ----------
    model_name : string
        The name of the absorption model.
    nH : float
        The foreground column density *nH* in units of 10^22 cm^{-2}.
    emin : float, optional
        The minimum energy for the spectral model.
    emax : float, optional
        The maximum energy for the spectral model.
    nchan : integer, optional
        The number of channels in the spectral model.
    settings : dictionary, optional
        A dictionary of key, value pairs (must both be strings)
        that can be used to set various options in XSPEC.

    Examples
    --------
    >>> abs_model = XSpecAbsorbModel("wabs", 0.1)
    """
    def __init__(self, model_name, nH, emin=0.01, emax=50.0,
                 nchan=100000, settings=None):
        mylog.warning("XSpecAbsorbModel is deprecated and will be removed "
                      "in a future release. Use of the other models is "
                      "suggested.")
        self.model_name = model_name
        self.nH = YTQuantity(nH*1.0e22, "cm**-2")
        if settings is None: settings = {}
        self.settings = settings
        self.emin = emin
        self.emax = emax
        self.nchan = nchan
        ebins = np.linspace(emin, emax, nchan+1)
        self.emid = YTArray(0.5*(ebins[1:]+ebins[:-1]), "keV")

    def prepare_spectrum(self):
        """
        Prepare the absorption model for execution.
        """
        import xspec
        xspec.Xset.chatter = 0
        xspec.AllModels.setEnergies("%f %f %d lin" %
                                    (self.emin, self.emax, self.nchan))
        self.model = xspec.Model(self.model_name+"*powerlaw")
        self.model.powerlaw.norm = self.nchan/(self.emax-self.emin)
        self.model.powerlaw.PhoIndex = 0.0
        for k,v in self.settings.items():
            xspec.Xset.addModelString(k,v)
        m = getattr(self.model, self.model_name)
        m.nH = 1.0
        self.sigma = YTArray(-np.log(self.model.values(0))*1.0e-22, "cm**2")

    def cleanup_spectrum(self):
        del self.model


class TableAbsorbModel(AbsorptionModel):
    r"""
    Initialize an absorption model from a table stored in an HDF5 file.

    Parameters
    ----------
    filename : string
        The name of the table file.
    nH : float
        The foreground column density *nH* in units of 10^22 cm^{-2}.

    Examples
    --------
    >>> abs_model = TableAbsorbModel("tbabs_table.h5", 0.1)
    """
    def __init__(self, filename, nH):
        self.filename = check_file_location(filename, "spectral_files")
        f = h5py.File(self.filename,"r")
        emid = YTArray(0.5*(f["energy"][1:]+f["energy"][:-1]), "keV")
        sigma = YTArray(f["cross_section"][:], "cm**2")
        f.close()
        super(TableAbsorbModel, self).__init__(nH, emid, sigma)

class TBabsModel(TableAbsorbModel):
    r"""
    Initialize a Tuebingen-Boulder (Wilms, J., Allen, A., & 
    McCray, R. 2000, ApJ, 542, 914) ISM absorption model.

    Parameters
    ----------
    nH : float
        The foreground column density *nH* in units of 10^22 cm^{-2}.

    Examples
    --------
    >>> tbabs_model = TBabsModel(0.1)
    """
    def __init__(self, nH):
        super(TBabsModel, self).__init__("tbabs_table.h5", nH)

class WabsModel(AbsorptionModel):
    r"""
    Initialize a Wisconsin (Morrison and McCammon; ApJ 270, 119) 
    absorption model.

    Parameters
    ----------
    nH : float
        The foreground column density *nH* in units of 10^22 cm^{-2}.

    Examples
    --------
    >>> wabs_model = WabsModel(0.1)
    """
    def __init__(self, nH):
        self.nH = YTQuantity(nH, "1.0e22*cm**-2")

    def get_absorb(self, e):
        e = np.array(e)
        return get_wabs_absorb(e, self.nH.v)
