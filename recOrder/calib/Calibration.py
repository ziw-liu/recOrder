import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import tifffile as tiff
import time
from recOrder.calib.CoreFunctions import define_lc_state, snap_image, set_lc, get_lc, set_lc_state
from recOrder.calib.Optimization import BrentOptimizer, MinScalarOptimizer, optimize_grid
from mpl_toolkits.axes_grid1.axes_divider import make_axes_locatable
import json
import os

#todo: save metadata without overwriting existing file
#todo: clean up plotting
#todo: enable logging


#TODO: Docstrings
class QLIPP_Calibration():
    # Meadowlark LC Device Adapter Property Names
    PROPERTIES = {'LCA': 'Retardance LC-A [in waves]',
                  'LCB': 'Retardance LC-B [in waves]',
                  'State0': 'Pal. elem. 00; enter 0 to define; 1 to activate',
                  'State1': 'Pal. elem. 01; enter 0 to define; 1 to activate',
                  'State2': 'Pal. elem. 02; enter 0 to define; 1 to activate',
                  'State3': 'Pal. elem. 03; enter 0 to define; 1 to activate',
                  'State4': 'Pal. elem. 04; enter 0 to define; 1 to activate',
                  }

    #todo: include wavelength, full_fov, etc. in init?
    def __init__(self, mmc, mm, optimization='min_scalar', print_details=True):

        # Micromanager API
        self.mm = mm
        self.mmc = mmc

        # GUI Emitter
        self.intensity_emitter = None
        self.log_emitter = None
        self.img_emitter = None

        # Optimizer
        if optimization == 'min_scalar':
            self.optimizer = MinScalarOptimizer(self)
        elif optimization == 'brent':
            self.optimizer = BrentOptimizer(self)
        else:
            raise ModuleNotFoundError(f'No optimizer named {optimization}')

        # User / Calculated Parameters
        self.swing = None
        self.wavelength = None
        self.lc_bound = None
        self.I_Black = None
        self.ROI = None
        self.ratio = 1.793
        self.print_details = print_details
        self.calib_scheme = '4-State'

        # LC States
        self.lca_ext = None
        self.lcb_ext = None
        self.lca_0 = None
        self.lcb_0 = None
        self.lca_45 = None
        self.lcb_45 = None
        self.lca_60 = None
        self.lcb_60 = None
        self.lca_90 = None
        self.lcb_90 = None
        self.lca_120 = None
        self.lcb_120 = None
        self.lca_135 = None
        self.lcb_135 = None

        # Calibration Outputs
        self.I_Ext = None
        self.I_Ref = None
        self.I_Elliptical = None
        self.inten = []
        self.swing0 = None
        self.swing45 = None
        self.swing60 = None
        self.swing90 = None
        self.swing120 = None
        self.swing135 = None
        self.height = None
        self.width = None
        self.directory = None
        self.inst_mat = None

    def opt_lc_simul(self, x, reference, normalize=False):

        print(f'LCA, LCB: {x[0], x[1]}')
        set_lc(self.mmc, x[0], self.PROPERTIES['LCA'])
        set_lc(self.mmc, x[1], self.PROPERTIES['LCB'])

        data = snap_image(self.mmc)
        mean = np.mean(data)

        self.emitter.emit(mean)
        self.inten.append(mean)

        if normalize:
            max_ = 65335
            min_ = self.I_Black

            val = (np.mean(data) - min_) / (max_ - min_)
            ref = (reference - min_) / (max_ - min_)

            print(f'F-Value:{val - ref}\n')
            return val - ref

        else:
            return np.abs(mean - reference)

    def opt_lc(self, x, device_property, reference, normalize=False):

        if isinstance(x, list) or isinstance(x, tuple):
            x = x[0]

        set_lc(self.mmc, x, device_property)

        data = snap_image(self.mmc)

        if normalize:
            max_ = 65335
            min_ = self.I_Black

            val = (np.mean(data) - min_) / (max_ - min_)
            ref = (reference - min_) / (max_ - min_)

            print(f'LC-Value: {x}')
            print(f'F-Value:{val - ref}\n')
            return val - ref

        else:
            mean = np.mean(data)
            # TODO: Change to just plotting mean?
            self.intensity_emitter.emit(mean)
            self.inten.append(mean - reference)

            return np.abs(mean - reference)

    def opt_lc_cons(self, x, reference, mode):

        set_lc(self.mmc, x, self.PROPERTIES['LCA'])
        swing = (self.lca_ext - x) * self.ratio

        if mode == '60':
            set_lc(self.mmc, self.lcb_ext + swing, self.PROPERTIES['LCB'])

        if mode == '120':
            set_lc(self.mmc, self.lcb_ext - swing, self.PROPERTIES['LCB'])

        data = snap_image(self.mmc)
        mean = np.mean(data)

        # append to intensity array for plotting later
        self.intensity_emitter.emit(mean)
        self.inten.append(mean - reference)

        return np.abs(mean - reference)

    # ========== Optimization wrappers =============
    # ==============================================
    def opt_Iext(self):
        print('Calibrating State0 (Extinction)...')

        set_lc_state(self.mmc, 'State0')
        time.sleep(2)

        # Perform exhaustive search with step 0.1 over range:
        # 0.01 < LCA < 0.5
        # 0.25 < LCB < 0.75
        step = 0.1
        if self.print_details:
            print(f"\n================================")
            print(f"Starting first grid search, step = {step}")
            print(f"================================")

        best_lca, best_lcb, i_ext_ = optimize_grid(self, 0.01, 0.5, 0.25, 0.75, step)

        if self.print_details:
            print("grid search done")
            print("lca = " + str(best_lca))
            print("lcb = " + str(best_lcb))
            print("intensity = " + str(i_ext_))

        set_lc(self.mmc, best_lca, self.PROPERTIES['LCA'])
        set_lc(self.mmc, best_lcb, self.PROPERTIES['LCB'])

        if self.print_details:
            print(f"\n================================")
            print(f"Starting fine search")
            print(f"================================")

        # Perform brent optimization around results of 2nd grid search
        # threshold not very necessary here as intensity value will
        # vary between exposure/lamp intensities
        lca, lcb, I_ext = self.optimizer.optimize(state='ext', lca_bound=0.1, lcb_bound=0.1,
                                                  reference=self.I_Black, thresh=1)

        # Set the Extinction state to values output from optimization
        define_lc_state(self.mmc, 'State0', lca, lcb, self.PROPERTIES)

        self.lca_ext = lca
        self.lcb_ext = lcb
        self.I_Ext = I_ext

        if self.print_details:
            print("fine search done")

        print("LCA Exinction = " + str(lca))
        print("LCB Exintction = " + str(lcb))
        print("Intensity = " + str(I_ext))

        # plot optimization details
        if self.print_details:
            I = np.copy(self.inten)
            plt.plot(I)
            plt.title('Intensity - Extinction')
            plt.ylabel('I - Ref')
            plt.show()

        print("--------done--------\n")

    def opt_I0(self):
        """
        no optimization performed for this.  Simply apply swing and read intensity
        This is the same as "Ielliptical".  Used for both schemes.
        :return: float
            mean of image
        """

        print('\nCalibrating State1 (I0)...')

        define_lc_state(self.mmc, 'State1', self.lca_ext - self.swing, self.lcb_ext, self.PROPERTIES)

        image = snap_image(self.mmc)
        ref = np.mean(image)

        self.lca_0 = self.lca_ext - self.swing
        self.lcb_0 = self.lcb_ext
        self.I_Elliptical = ref
        self.swing0 = np.sqrt((self.lcb_0 - self.lcb_ext) ** 2 + (self.lca_0 - self.lca_ext) ** 2)

        print(f'Intensity = {ref}')

        print("--------done--------")

    def opt_I45(self, lca_bound, lcb_bound):
        """
        optimized relative to Ielliptical (opt_I90)
        Parameters
        ----------
        lca_bound
        lcb_bound

        Returns
        -------
        lca, lcb value at optimized state
        intensity value at optimized state

        """
        self.inten = []
        print('\nCalibrating State2 (I45)...')

        set_lc(self.mmc, self.lca_ext, self.PROPERTIES['LCA'])
        set_lc(self.mmc, self.lcb_ext - self.swing, self.PROPERTIES['LCB'])

        self.lca_45, self.lcb_45, intensity = self.optimizer.optimize('45', lca_bound, lcb_bound,
                                                                      reference=self.I_Elliptical, n_iter=5, thresh=.01)

        define_lc_state(self.mmc, 'State2', self.lca_45, self.lcb_45, self.PROPERTIES)

        self.swing45 = np.sqrt((self.lcb_45 - self.lcb_ext) ** 2 + (self.lca_45 - self.lca_ext) ** 2)

        if self.print_details:
            I = np.copy(self.inten)
            plt.plot(I)
            plt.title('Intensity - State2')
            plt.ylabel('I - Ref')
            plt.show()

        print("--------done--------")

    def opt_I60(self, lca_bound, lcb_bound):
        """
        optimized relative to Ielliptical (opt_I0_4State)
        Parameters
        ----------
        lca_bound
        lcb_bound

        Returns
        -------
        lca, lcb value at optimized state
        intensity value at optimized state

        """
        self.inten = []

        print('\nCalibrating State2 (I60)...')

        # Calculate Initial Swing for initial guess to optimize around
        # Based on ratio calculated from ellpiticity/orientation of LC simulation
        swing_ell = np.sqrt((self.lca_ext - self.lca_0) ** 2 + (self.lcb_ext - self.lcb_0) ** 2)
        lca_swing = np.sqrt(swing_ell ** 2 / (1 + self.ratio ** 2))
        lcb_swing = self.ratio * lca_swing

        # Optimization
        set_lc(self.mmc, self.lca_ext + lca_swing, self.PROPERTIES['LCA'])
        set_lc(self.mmc, self.lcb_ext + lcb_swing, self.PROPERTIES['LCB'])

        self.lca_60, self.lcb_60, intensity = self.optimizer.optimize('60', lca_bound, lcb_bound,
                                                                      reference=self.I_Elliptical,
                                                                      n_iter=5, thresh=.01)

        define_lc_state(self.mmc, 'State2', self.lca_60, self.lcb_60, self.PROPERTIES)

        self.swing60 = np.sqrt((self.lcb_60 - self.lcb_ext) ** 2 + (self.lca_60 - self.lca_ext) ** 2)

        # Print comparison of target swing, target ratio
        # Ratio determines the orientation of the elliptical state
        # should be close to target.  Swing will vary to optimize ellipticity
        #todo: remove targets from detailed print?
        # We know that the theoretical targets do not reflect true LC state accurate
        if self.print_details:
            print(f'ratio: swing_LCB / swing_LCA = {(self.lcb_ext - self.lcb_60) / (self.lca_ext - self.lca_60):.4f} \
                  | target ratio: {-self.ratio}')
            print(f'total swing = {self.swing60:.4f} | target = {swing_ell}')

            I = np.copy(self.inten)
            plt.plot(I)
            plt.title('Intensity - State60')
            plt.ylabel('I - Ref')
            plt.show()

        print("--------done--------")

    def opt_I90(self, lca_bound, lcb_bound):
        """
        optimized relative to Ielliptical (opt_I90)
        Parameters
        ----------
        lca_bound
        lcb_bound

        Returns
        -------
        lca, lcb value at optimized state
        intensity value at optimized state

        """
        print('\nCalibrating State3 (I90)...')
        self.inten = []

        set_lc(self.mmc, self.lca_ext + self.swing, self.PROPERTIES['LCA'])
        set_lc(self.mmc, self.lcb_ext, self.PROPERTIES['LCB'])

        self.lca_90, self.lcb_90, intensity = self.optimizer.optimize('90', lca_bound, lcb_bound,
                                                                      reference=self.I_Elliptical,
                                                                      n_iter=5, thresh=.01)

        define_lc_state(self.mmc, 'State3', self.lca_90, self.lcb_90, self.PROPERTIES)

        self.swing90 = np.sqrt((self.lcb_90 - self.lcb_ext) ** 2 + (self.lca_90 - self.lca_ext) ** 2)

        if self.print_details:
            I = np.copy(self.inten)
            plt.plot(I)
            plt.title('Intensity - State3')
            plt.ylabel('I - Ref')
            plt.show()

        print("--------done--------")

    def opt_I120(self, lca_bound, lcb_bound):
        """
        optimized relative to Ielliptical (opt_I0_4State)

        Parameters
        ----------
        lca_bound
        lcb_bound

        Returns
        -------
        lca, lcb value at optimized state
        intensity value at optimized state

        """
        print('\nCalibrating State3 (I120)...\n')
        self.inten = []

        # Calculate Initial Swing for initial guess to optimize around
        # Based on ratio calculated from ellpiticity/orientation of LC simulation
        swing_ell = np.sqrt((self.lca_ext - self.lca_0) ** 2 + (self.lcb_ext - self.lcb_0) ** 2)
        lca_swing = np.sqrt(swing_ell ** 2 / (1 + self.ratio ** 2))
        lcb_swing = self.ratio * lca_swing

        # Brent Optimization
        set_lc(self.mmc, self.lca_ext + lca_swing, self.PROPERTIES['LCA'])
        set_lc(self.mmc, self.lcb_ext - lcb_swing, self.PROPERTIES['LCB'])

        self.lca_120, self.lcb_120, intensity = self.optimizer.optimize('120', lca_bound, lcb_bound,
                                                                      reference=self.I_Elliptical,
                                                                      n_iter=5, thresh=.01)

        define_lc_state(self.mmc, 'State3', self.lca_120, self.lcb_120, self.PROPERTIES)

        self.swing120 = np.sqrt((self.lcb_120 - self.lcb_ext) ** 2 + (self.lca_120 - self.lca_ext) ** 2)

        # Print comparison of target swing, target ratio
        # Ratio determines the orientation of the elliptical state
        # should be close to target.  Swing will vary to optimize ellipticity
        #todo: remove targets?
        if self.print_details:
            print(f'ratio: swing_LCB / swing_LCA = {(self.lcb_ext - self.lcb_120) / (self.lca_ext - self.lca_120):.4f}\
             | target ratio: {self.ratio}')
            print(f'total swing = {self.swing120:.4f} | target = {swing_ell}')

            I = np.copy(self.inten)
            plt.plot(I)
            plt.title('Intensity - State120')
            plt.ylabel('I - Ref')
            plt.show()

        print("--------done--------")

    def opt_I135(self, lca_bound, lcb_bound):
        """
        optimized relative to Ielliptical (opt_I0)
        Parameters
        ----------
        lca_bound
        lcb_bound

        Returns
        -------
        lca, lcb value at optimized state
        intensity value at optimized state

        """
        print('\nCalibrating State4 (I135)...')
        self.inten = []

        set_lc(self.mmc, self.lca_ext, self.PROPERTIES['LCA'])
        set_lc(self.mmc, self.lcb_ext + self.swing, self.PROPERTIES['LCB'])

        self.lca_135, self.lcb_135, intensity = self.optimizer.optimize('135', lca_bound, lcb_bound,
                                                                      reference=self.I_Elliptical,
                                                                      n_iter=5, thresh=.01)

        define_lc_state(self.mmc, 'State4', self.lca_135, self.lcb_135, self.PROPERTIES)

        self.swing135 = np.sqrt((self.lcb_135 - self.lcb_ext) ** 2 + (self.lca_135 - self.lca_ext) ** 2)

        # plot details of brent optimization
        if self.print_details:
            I = np.copy(self.inten)
            plt.plot(I)
            plt.title('Intensity - State4')
            plt.ylabel('I - Ref')
            plt.show()

        print("--------done--------")

    def calc_blacklevel(self):

        auto_shutter = self.mmc.getAutoShutter()
        shutter = self.mmc.getShutterOpen()

        self.mmc.setAutoShutter(False)
        self.mmc.setShutterOpen(False)

        n_avg = 20
        avgs = []
        for i in range(n_avg):
            img = snap_image(self.mmc)
            # print(np.mean(img))
            avgs.append(np.mean(img))

        blacklevel = np.mean(avgs)

        self.mmc.setAutoShutter(auto_shutter)

        if not auto_shutter:
            self.mmc.setShutterOpen(shutter)

        self.I_black = blacklevel
        return blacklevel

    def get_full_roi(self):
        # Get Image Parameters
        self.mmc.snapImage()
        self.mmc.getImage()
        self.height, self.width = self.mmc.getImageHeight(), self.mmc.getImageWidth()
        self.ROI = (0, 0, self.width, self.height)

    def check_and_get_roi(self):

        windows = self.mm.displays().getAllImageWindows()
        size = windows.size()

        boxes = []
        for i in range(size):
            win = windows.get(i).toFront()
            time.sleep(0.05)
            roi = self.mm.displays().getActiveDataViewer().getImagePlus().getRoi()
            if roi != None:
                boxes.append(roi)

        if len(boxes) == 0:
            raise ValueError('No ROI Bounding Box Found, Please Draw Bounding Box on the Preview (live) Window')

        if len(boxes) > 1:
            raise ValueError('More than one Bounding Box Found, Please Remove any box not on the preview (live) window')

        if len(boxes) == 1:
            rect = boxes[0].getBounds()
            return rect

    def display_and_check_ROI(self, rect):

        img = snap_image(self.mmc)

        print('Will Calibrate Using this ROI:')
        fig, ax = plt.subplots()

        ax.imshow(np.reshape(img, (self.height, self.width)), 'gray')
        box = patches.Rectangle((rect.x, rect.y), rect.width, rect.height, linewidth=2, edgecolor='r', facecolor='none')
        ax.add_patch(box)
        plt.show()

        cont = input('Would You Like to Calibrate Using this ROI? (Yes/No): \t')

        if cont in ['Yes', 'Y', 'yes', 'ye', 'y', '']:
            return True

        if cont in ['No', 'N', 'no', 'n']:
            return False

        else:
            raise ValueError('Did not understand your answer, please check spelling')

    def run_5state_calibration(self, param):
        """
        Param is a list or tuple of:
            (swing, wavelength, lc_bounds, black level)
        """
        self.swing = param[0]
        self.wavelength = param[1]
        self.meta_file = param[2]
        use_full_FOV = param[3]

        # Get Image Parameters
        self.mmc.snapImage()
        self.mmc.getImage()
        self.height, self.width = self.mmc.getImageHeight(), self.mmc.getImageWidth()
        self.ROI = (0, 0, self.width, self.height)

        # Check if change of ROI is needed
        if use_full_FOV is False:
            rect = self.check_and_get_roi()
            cont = self.display_and_check_ROI(rect)

            if not cont:
                print('\n---------Stopping Calibration---------\n')
                return
            else:
                self.mmc.setROI(rect.x, rect.y, rect.width, rect.height)
                self.ROI = (rect.x, rect.y, rect.width, rect.height)

        # Calculate Blacklevel
        print('Calculating Blacklevel ...')
        self.I_Black = self.calc_blacklevel()
        print(f'Blacklevel: {self.I_Black}\n')

        # Set LC Wavelength:
        self.mmc.setProperty('MeadowlarkLcOpenSource', 'Wavelength', self.wavelength)

        self.opt_Iext()
        self.opt_I0()
        self.opt_I45(0.05, 0.05)
        self.opt_I90(0.05, 0.05)
        self.opt_I135(0.05, 0.05)

        # Calculate Extinction
        self.extinction_ratio = self.calculate_extinction()

        # Write Metadata
        self.write_metadata(5)

        # Return ROI to full FOV
        if use_full_FOV is False:
            self.mmc.clearROI()

        print("\n=======Finished Calibration=======\n")
        print(f"EXTINCTION = {self.extinction_ratio}")

    def run_4state_calibration(self, param):
        """
        Param is a list or tuple of:
            (swing, wavelength, lc_bounds, black level, <mode>)
            where <mode> is one of 'full','coarse','fine'
        """
        self.swing = param[0]
        self.wavelength = param[1]
        self.meta_file = param[2]
        use_full_FOV = param[3]

        # Get Image Parameters
        self.mmc.snapImage()
        self.mmc.getImage()
        self.height, self.width = self.mmc.getImageHeight(), self.mmc.getImageWidth()
        self.ROI = (0, 0, self.width, self.height)

        # Check if change of ROI is needed
        if use_full_FOV is False:
            rect = self.check_and_get_roi()
            cont = self.display_and_check_ROI(rect)

            if not cont:
                print('\n---------Stopping Calibration---------\n')
                return
            else:
                self.mmc.setROI(rect.x, rect.y, rect.width, rect.height)
                self.ROI = (rect.x, rect.y, rect.width, rect.height)

        # Calculate Blacklevel
        print('Calculating Blacklevel ...')
        self.I_Black = self.calc_blacklevel()
        print(f'Blacklevel: {self.I_Black}\n')

        # Set LC Wavelength:
        self.mmc.setProperty('MeadowlarkLcOpenSource', 'Wavelength', self.wavelength)

        self.opt_Iext()
        self.opt_I0()
        self.opt_I60(0.05, 0.05)
        self.opt_I120(0.05, 0.05)

        # Calculate Extinction
        self.extinction_ratio = self.calculate_extinction()

        # Write Metadata
        self.write_metadata(4)

        # Return ROI to full FOV
        if use_full_FOV is False:
            self.mmc.clearROI()

        print("\n=======Finished Calibration=======\n")
        print(f"EXTINCTION = {self.extinction_ratio}")

    def run_calibration(self, scheme, options):

        if scheme == '5-State':
            self.run_5state_calibration(options)

        elif scheme == '4-State Extinction':
            self.run_4state_calibration(options)

        else:
            raise ValueError('Please define the calibration scheme')

    def calculate_extinction(self):
        return (1 / np.sin(np.pi * self.swing) ** 2) * (self.I_Elliptical - self.I_Black) / (self.I_Ext - self.I_Black)

    def calc_inst_matrix(self, n_states):

        if n_states == 4:
            chi = self.swing
            inst_mat = np.array([[1, 0, 0, -1],
                                 [1, np.sin(2 * np.pi * chi), 0, -np.cos(2 * np.pi * chi)],
                                 [1, -0.5 * np.sin(2 * np.pi * chi),
                                  np.sqrt(3) * np.cos(np.pi * chi) * np.sin(np.pi * chi), -np.cos(2 * np.pi * chi)],
                                 [1, -0.5 * np.sin(2 * np.pi * chi), -np.sqrt(3) / 2 * np.sin(2 * np.pi * chi),
                                  -np.cos(2 * np.pi * chi)]])

            return inst_mat

        if n_states == 5:
            chi = self.swing * 2 * np.pi

            inst_mat = np.array([[1, 0, 0, -1],
                                 [1, np.sin(chi), 0, -np.cos(chi)],
                                 [1, 0, np.sin(chi), -np.cos(chi)],
                                 [1, -np.sin(chi), 0, -np.cos(chi)],
                                 [1, 0, -np.sin(chi), -np.cos(chi)]])

            return inst_mat

    def write_metadata(self, n_states):
        """ Function to write a metadata file for calibration.
            This follows the PolAcqu metadata file format and is compatible with
            reconstruct-order

        :param: n_states (int)
            Number of states used for calibration
        :param: directory (string)
            Directory to save metadata file.

        """
        inst_mat = self.calc_inst_matrix(n_states)
        inst_mat = inst_mat.tolist()

        if n_states == 4:
            data = {'Summary':
                    {'Acquired Using': '4-Frame Extinction',
                     'Swing (fraction)': self.swing,
                     'Wavelength (nm)': self.wavelength,
                     'BlackLevel': self.I_Black,
                     'ChNames': ["State0", "State1", "State2", "State3"],
                     '[LCA_Ext, LCB_Ext]': [self.lca_ext, self.lcb_ext],
                     '[LCA_0, LCB_120]': [self.lca_0, self.lcb_0],
                     '[LCA_60, LCB_60]': [self.lca_60, self.lcb_60],
                     '[LCA_120, LCB_120]': [self.lca_120, self.lcb_120],
                     'Swing0': self.swing0,
                     'Swing60': self.swing60,
                     'Swing120': self.swing120,
                     'Extinction Ratio': self.extinction_ratio,
                     'ROI Used (x, y, width, height)': self.ROI,
                     'Instrument_Matrix': inst_mat}
                    }

        elif n_states == 5:
            data = {'Summary':
                    {'Acquired Using': '5-Frame',
                     'Swing (fraction)': self.swing,
                     'Wavelength (nm)': self.wavelength,
                     'BlackLevel': self.I_Black,
                     'ChNames': ["State0", "State1", "State2", "State3", "State4"],
                     '[LCA_Ext, LCB_Ext]': [self.lca_ext, self.lcb_ext],
                     '[LCA_0, LCB_0]': [self.lca_0, self.lcb_0],
                     '[LCA_45, LCB_45]': [self.lca_45, self.lcb_45],
                     '[LCA_90, LCB_90]': [self.lca_90, self.lcb_90],
                     '[LCA_135, LCB_135]': [self.lca_135, self.lcb_135],
                     'Swing0': self.swing0,
                     'Swing45': self.swing45,
                     'Swing90': self.swing90,
                     'Swing135': self.swing135,
                     'Extinction Ratio': self.extinction_ratio,
                     'ROI Used (x, y, width, height)': self.ROI,
                     'Instrument_Matrix': inst_mat}
                    }

        if not self.meta_file.endswith('.txt'):
            self.meta_file += '.txt'

        with open(self.meta_file, 'w') as metafile:
            json.dump(data, metafile, indent=1)

    def _add_colorbar(self, mappable):
        last_axes = plt.gca()
        ax = mappable.axes
        fig = ax.figure
        divider = make_axes_locatable(ax)
        cax = divider.append_axes("right", size="5%", pad=0.05)
        cbar = fig.colorbar(mappable, cax=cax)
        plt.sca(last_axes)
        return cbar

    def _capture_state(self, state, n_avg):
        set_lc_state(self.mmc, state)

        state0 = []
        for i in range(n_avg):
            state0.append(np.reshape(snap_image(self.mmc), newshape=(self.height, self.width)))

        return np.mean(state0, axis=(0))

    def _plot_bg_images(self, imgs):

        img_names = ['Extinction', '0', '60', '120'] if len(imgs) == 4 else ['Extinction', '0', '45', '90', 135]
        fig, ax = plt.subplots(2, 2, figsize=(20, 20)) if len(imgs) == 4 else plt.subplots(3, 2, figsize=(20, 20))

        img_idx = 0
        for ax1 in range(len(ax[:, 0])):
            for ax2 in range(len(ax[0, :])):
                if img_idx < len(imgs):
                    im = ax[ax1, ax2].imshow(imgs[img_idx], 'gray')
                    ax[ax1, ax2].set_title(img_names[img_idx])
                    self._add_colorbar(im)
                else:
                    try:
                        fig.delaxes(ax[2, 1])
                    except:
                        break
        plt.show()


    def capture_bg(self, n_avg, directory):
        """"
        This function will capture an image at every state
        and save to specified directory
        This may throw errors depending on the micromanager config file--
        modify 'State_' to match to the corresponding channel preset in config

        :param: n_states (int)
            Number of states used for calibration
        :param: directory (string)
            Directory to save images

        """

        if not os.path.exists(directory):
            os.makedirs(directory)

        self.height, self.width = self.mmc.getImageHeight(), self.mmc.getImageWidth()

        state0 = self._capture_state('State0', n_avg)
        tiff.imsave(os.path.join(directory, 'State0.tif'), state0)

        state1 = self._capture_state('State1', n_avg)
        tiff.imsave(os.path.join(directory, 'State1.tif'), state1)

        state2 = self._capture_state('State2', n_avg)
        tiff.imsave(os.path.join(directory, 'State2.tif'), state2)

        state3 = self._capture_state('State3', n_avg)
        tiff.imsave(os.path.join(directory, 'State3.tif'), state3)

        imgs = [state0, state1, state2, state3]

        if self.calib_scheme == '5-State':
            state4 = self._capture_state('State4', n_avg)
            tiff.imsave(os.path.join(directory, 'State4.tif'), state4)
            imgs.append(state4)

        self._plot_bg_images(np.asarray(imgs))

        return np.asarray(imgs)
