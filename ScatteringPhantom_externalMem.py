import numpy
#import threading
#import multiprocessing
#import ctypes
#from scipy import linalg
from scipy import ndimage
from keras.preprocessing.image import load_img, img_to_array, array_to_img#, save_img
from keras.utils import Sequence
import glob
#from PIL import Image
from skimage import util
from skimage import transform
import itertools
import os
import re
import h5py


WORKERS = 8
CACHE_SIZE = 32

def clipped_zoom(img, zoom_factor, **kwargs):

    h, w = img.shape[:2]

    # For multichannel images we don't want to apply the zoom factor to the RGB
    # dimension, so instead we create a tuple of zoom factors, one per array
    # dimension, with 1's for any trailing dimensions after the width and height.
    zoom_tuple = (zoom_factor,) * 2 + (1,) * (img.ndim - 2)

    # Zooming out
    if zoom_factor < 1:

        # Bounding box of the zoomed-out image within the output array
        zh = int(numpy.round(h * zoom_factor))
        zw = int(numpy.round(w * zoom_factor))
        top = (h - zh) // 2
        left = (w - zw) // 2

        # Zero-padding
        out = numpy.zeros_like(img)
        out[top:top+zh, left:left+zw] = ndimage.zoom(img, zoom_tuple, **kwargs)

    # Zooming in
    elif zoom_factor > 1:

        # Bounding box of the zoomed-in region within the input array
        zh = int(numpy.round(h / zoom_factor))
        zw = int(numpy.round(w / zoom_factor))
        top = (h - zh) // 2
        left = (w - zw) // 2

        out = ndimage.zoom(img[top:top+zh, left:left+zw], zoom_tuple, **kwargs)

        # `out` might still be slightly larger than `img` due to rounding, so
        # trim off any extra pixels at the edges
        trim_top = ((out.shape[0] - h) // 2)
        trim_left = ((out.shape[1] - w) // 2)
        out = out[trim_top:trim_top+h, trim_left:trim_left+w]

    # If zoom_factor == 1, just return the input array
    else:
        out = img
    return out

def numpy_normalize(v):
    norm = numpy.linalg.norm(v)
    if norm == 0:
        return v
    return v/norm

def get_min_max(a, numChannels, minx=None, maxx=None):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    if numChannels<=1:
        if minx is None:
            minx = numpy.min(a)
        if maxx is None:
            maxx = numpy.max(a)
    else:
        if minx is None:
            minx = []
        if maxx is None:
            maxx = []
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if len(minx) < numChannels:
                    minx.append(numpy.min(a[:, :, channelIdx]))
                if len(maxx) < numChannels:
                    maxx.append(numpy.max(a[:, :, channelIdx]))
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if len(minx) < numChannels:
                    minx.append(numpy.min(a[:, :, :, channelIdx]))
                if len(maxx) < numChannels:
                    maxx.append(numpy.max(a[:, :, :, channelIdx]))
    #print(("{} in vs {} out vs {} a-shape".format(inShape,outShape, a.shape)))
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return minx, maxx

def normaliseFieldArray(a, numChannels, minx=None, maxx=None):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    if numChannels<=1:
        if minx is None:
            minx = numpy.min(a)
        if maxx is None:
            maxx = numpy.max(a)
        a = (a - minx) / (maxx-minx)
    else:
        if minx is None:
            minx = []
        if maxx is None:
            maxx = []
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if len(minx) < numChannels:
                    minx.append(numpy.min(a[:, :, channelIdx]))
                if len(maxx) < numChannels:
                    maxx.append(numpy.max(a[:, :, channelIdx]))
                if numpy.fabs(maxx[channelIdx] - minx[channelIdx]) > 0:
                    a[:, :, channelIdx] = (a[:, :, channelIdx] - minx[channelIdx]) / (maxx[channelIdx] - minx[channelIdx])
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if len(minx) < numChannels:
                    minx.append(numpy.min(a[:, :, :, channelIdx]))
                if len(maxx) < numChannels:
                    maxx.append(numpy.max(a[:, :, :, channelIdx]))
                if numpy.fabs(maxx[channelIdx] - minx[channelIdx]) > 0:
                    a[:, :, :, channelIdx] = (a[:, :, :, channelIdx] - minx[channelIdx]) / (maxx[channelIdx] - minx[channelIdx])
    #print(("{} in vs {} out vs {} a-shape".format(inShape,outShape, a.shape)))
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return minx, maxx, a

def denormaliseFieldArray(a, numChannels, minx=None, maxx=None):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    if numChannels <= 1:
        a = a * (maxx - minx) + minx
    else:
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                a[:, :, channelIdx] = a[:, :, channelIdx] * (maxx[channelIdx] - minx[channelIdx]) + minx[channelIdx]
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                a[:, :, :, channelIdx] = a[:, :, :, channelIdx] * (maxx[channelIdx] - minx[channelIdx]) + minx[channelIdx]
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return a

def notnormaliseFieldArray(a, numChannels, minx=None, maxx=None):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    if numChannels<=1:
        if minx is None:
            minx = numpy.min(a)
        if maxx is None:
            maxx = numpy.max(a)
        a = a
    else:
        if minx is None:
            minx = []
        if maxx is None:
            maxx = []
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if len(minx) < numChannels:
                    minx.append(numpy.min(a[:, :, channelIdx]))
                if len(maxx) < numChannels:
                    maxx.append(numpy.max(a[:, :, channelIdx]))
                if numpy.fabs(maxx[channelIdx] - minx[channelIdx]) > 0:
                    a=a
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if len(minx) < numChannels:
                    minx.append(numpy.min(a[:, :, :, channelIdx]))
                if len(maxx) < numChannels:
                    maxx.append(numpy.max(a[:, :, :, channelIdx]))
                if numpy.fabs(maxx[channelIdx] - minx[channelIdx]) > 0:
                    a=a
    #print(("{} in vs {} out vs {} a-shape".format(inShape,outShape, a.shape)))
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return minx, maxx, a

def notdenormaliseFieldArray(a, numChannels, minx=None, maxx=None):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    if numChannels <= 1:
        a=a
    else:
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                a=a
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                a=a
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return a
    
def clipNormFieldArray(a, numChannels):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    minx = None
    maxx = None

    if numChannels <= 1:
        minx = 0
        maxx = 200.0
        a = numpy.clip(a,minx,maxx)
    else:
        minx = numpy.zeros(32, a.dtype)
        # IRON-CAP
        #maxx = numpy.array([197.40414602,164.05027316,136.52565589,114.00212036,95.65716526,80.58945472,67.46342114,56.09140486,45.31409774,37.64459755,31.70887797,26.41859429,21.9482954,18.30031205,15.31461954,12.82080624,10.70525853,9.17048875,7.82142154,6.7137903,5.82180097,5.01058597,4.41808895,3.81359458,3.40606635,3.01021494,2.76689262,2.47842852,2.32304044,2.12137244,15.00464109,33.07879503], a.dtype)
        # SCANDIUM-CAP
        maxx = numpy.array([40.77704764,33.66334239,27.81001556,22.99326739,19.0324146,15.68578289,12.92738646,10.67188431,8.82938367,7.32395058,6.09176207,5.08723914,4.25534357,3.58350332,3.0290752,2.57537332,2.20811373,1.8954763,1.64371557,1.43238593,1.27925194,1.24131863,1.11358517,1.08348688,1.03346652,0.95083789,0.9814638,0.87886442,1.06108008,1.4744603,1.37953941,1.33551697])
        for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
            a[:, :, channelIdx] = numpy.clip(a[:, :, channelIdx], minx[channelIdx], maxx[channelIdx])
    if numChannels<=1:
        a = ((a - minx) / (maxx-minx)) * 2.0 - 1.0
    else:
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if numpy.fabs(maxx[channelIdx] - minx[channelIdx]) > 0:
                    a[:, :, channelIdx] = ((a[:, :, channelIdx] - minx[channelIdx]) / (maxx[channelIdx] - minx[channelIdx])) * 2.0 - 1.0
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                if numpy.fabs(maxx[channelIdx] - minx[channelIdx]) > 0:
                    a[:, :, :, channelIdx] = ((a[:, :, :, channelIdx] - minx[channelIdx]) / (maxx[channelIdx] - minx[channelIdx])) * 2.0 - 1.0
    #print(("{} in vs {} out vs {} a-shape".format(inShape,outShape, a.shape)))
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return minx, maxx, a

def denormFieldArray(a, numChannels, minx=None, maxx=None):
    inShape = a.shape
    inDimLen = len(inShape)
    a = numpy.squeeze(a)
    outShape = a.shape
    outDimLen = len(outShape)
    if numChannels <= 1:
        a = ((a + 1.0) / 2.0) * (maxx - minx) + minx
    else:
        if outDimLen < 4:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                a[:, :, channelIdx] = ((a[:, :, channelIdx] + 1.0) / 2.0) * (maxx[channelIdx] - minx[channelIdx]) + minx[channelIdx]
        else:
            for channelIdx in itertools.islice(itertools.count(), 0, numChannels):
                a[:, :, :, channelIdx] = ((a[:, :, :, channelIdx] + 1.0) / 2.0) * (maxx[channelIdx] - minx[channelIdx]) + minx[channelIdx]
    if outDimLen<inDimLen:
        a = a.reshape(inShape)
    return a


class ScatterPhantomGenerator(Sequence):
    
    def __init__(self, batch_size=1, image_size=(128, 128), input_channels=32, target_size=(128, 128), output_channels=1, useResize=False,
                 useCrop=False, useZoom=False, zoom_factor_range=(0.95,1.05), useAWGN = False, useMedian=False, useGaussian=False,
                 useFlipping=False, useNormData=False, cache=None, save_to_dir=None, save_format="png", threadLockVar=None, useCache=False):
        self.batch_size = batch_size
        self.image_size = image_size
        self.target_size = target_size
        self.input_channels = input_channels
        self.output_channels = output_channels
        self.x_dtype_in = None
        self.y_dtype_in = None
        self.useResize = useResize
        self.useCrop = useCrop
        self.useAWGN = useAWGN
        self.useZoom = useZoom
        self.zoom_factor_range = zoom_factor_range
        self.useFlipping = useFlipping
        self.useMedian = useMedian
        self.medianSize = [0,1,3,5,7,9,11]
        self.useGaussian = useGaussian
        self.gaussianRange = (0, 0.075)
        self.useNormData = useNormData
        self._epoch_num_ = 0
        self.numImages = 0

        #self.numImages = 0
        #dims = (target_size[0], target_size[1], input_channels)
        #self.targetSize = (self.targetSize[0], self.targetSize[1], self.image_size[2])
        # ========================================#
        # == zoom-related image information ==#
        # ========================================#
        self.im_center = None
        self.im_shift = None
        self.im_bounds = None
        self.im_center = numpy.array([int(self.target_size[0] - 1) / 2, int(self.target_size[1] - 1) / 2], dtype=numpy.int32)
        self.im_shift = numpy.array([(self.image_size[0] - 1) / 2, (self.image_size[1] - 1) / 2], dtype=numpy.int32)
        left = max(self.im_shift[0] - self.im_center[0],0)
        right = min(left + self.target_size[0],self.image_size[0])
        top = max(self.im_shift[1] - self.im_center[1],0)
        bottom = min(top + self.target_size[1],self.image_size[1])
        self.im_bounds = (left, right, top, bottom)

        #===================================#
        #== directory-related information ==#
        #===================================#
        self.fileArray = []
        self.in_dir = ""
        self.save_to_dir=save_to_dir
        self.save_format=save_format
        self.store_img = True
        #===============================#
        #== caching-related variables ==#
        #===============================#
        self.useCache = useCache
        self.cache = cache
        self._lock_ = threadLockVar
        self.pid = 0
        self.seeded = False
        self._nsteps = int(numpy.ceil(len(self.fileArray)/float(self.batch_size)))
        #======================#
        #== batch size setup ==#
        #======================#
        self.batch_image_size_X = (self.batch_size, self.image_size[0], self.image_size[1], self.input_channels, 1)
        self.batch_image_size_Y = (self.batch_size, self.image_size[0], self.image_size[1], self.output_channels, 1)
        if self.useCrop or self.useResize:
            self.batch_image_size_X = (self.batch_size, self.target_size[0], self.target_size[1], self.input_channels, 1)
            self.batch_image_size_Y = (self.batch_size, self.target_size[0], self.target_size[1], self.output_channels, 1)
        
    def prepareDirectFileInput(self, input_image_paths):
        for entry in input_image_paths:
            for name in glob.glob(os.path.join(entry, '*.h5')):
                self.fileArray.append(name)
        digits = re.compile(r'(\d+)')
        def tokenize(filename):
            return tuple(int(token) if match else token for token, match in
                         ((fragment, digits.search(fragment)) for fragment in digits.split(filename)))
        # = Now you can sort your file names like so: =#
        self.fileArray.sort(key=tokenize)
        self.numImages = len(self.fileArray)

        # === prepare image sizes === #
        inImgDims = (self.image_size[0], self.image_size[1], self.input_channels, 1)
        outImgDims = (self.image_size[0], self.image_size[1], self.output_channels, 1)

        if len(self.fileArray) and os.path.exists(self.fileArray[0]):
            self.in_dir = os.path.dirname(self.fileArray[0])
            f = h5py.File(self.fileArray[0], 'r')
            # define your variable names in here
            imX = numpy.array(f['Data_X'], order='F').transpose()
            f.close()
            self.x_dtype_in = imX.dtype
            if len(imX.shape) > 3:
                imX = numpy.squeeze(imX[:, :, 0, :])
            if len(imX.shape) < 3:
                imX = imX.reshape(imX.shape + (1,))
            # === we need to feed the data as 3D+1 channel data stack === #
            if len(imX.shape) < 4:
                imX = imX.reshape(imX.shape + (1,))

            if imX.shape != inImgDims:
                print("Error - read data shape ({}) and expected data shape ({}) of X are not equal. EXITING ...".format(imX.shape, inImgDims))
                exit()

        if len(self.fileArray) and os.path.exists(self.fileArray[0]):
            f = h5py.File(self.fileArray[0], 'r')
            # define your variable names in here
            imY = numpy.array(f['Data_Y'], order='F').transpose()
            f.close()
            self.y_dtype_in = imY.dtype
            if len(imY.shape) > 3:
                imY = numpy.squeeze(imY[:,:,0,:])
            if len(imY.shape) < 3:
                imY = imY.reshape(imY.shape + (1,))
            # === we need to feed the data as 3D+1 channel data stack === #
            if len(imY.shape) < 4:
                imY = imY.reshape(imY.shape + (1,))

            if imY.shape != outImgDims:
                print("Error - read data shape ({}) and expected data shape ({}) of X are not equal. EXITING ...".format(imX.shape,inImgDims))
                exit()

        # ======================================== #
        # ==== crop-related image information ==== #
        # ======================================== #
        self.im_center = None
        self.im_shift = None
        self.im_bounds = None
        self.im_center = numpy.array([int(self.target_size[0] - 1) / 2, int(self.target_size[1] - 1) / 2], dtype=numpy.int32)
        self.im_shift = numpy.array([(self.image_size[0] - 1) / 2, (self.image_size[1] - 1) / 2], dtype=numpy.int32)
        left = max(self.im_shift[0] - self.im_center[0],0)
        right = min(left + self.target_size[0],self.image_size[0])
        top = max(self.im_shift[1] - self.im_center[1],0)
        bottom = min(top + self.target_size[1],self.image_size[1])
        self.im_bounds = (left, right, top, bottom)

    def _initCache_locked_(self):
        loadData_flag = True
        while (loadData_flag):
            ii = 0
            with self._lock_:
                loadData_flag = (self.cache.is_cache_updated() == False)
                ii=self.cache.get_renew_index()
            if loadData_flag == False:
                break
            file_index = numpy.random.randint(0, self.numImages)
            inName = self.fileArray[file_index]
            f = h5py.File(inName, 'r')
            imX = numpy.array(f['Data_X'], order='F').transpose()
            imY = numpy.array(f['Data_Y'], order='F').transpose()
            f.close()
            if len(imX.shape) != len(imY.shape):
                print("Image dimensions do not match - EXITING ...")
                exit(1)

            if len(imX.shape) > 3:
                indices = [ii,]
                while (len(indices)<imX.shape[2]) and (loadData_flag==True):
                    with self._lock_:
                        ii = self.cache.get_renew_index()
                        indices.append(ii)
                    with self._lock_:
                        loadData_flag = (self.cache.is_cache_updated() == False)
                slice_indices = numpy.random.randint(0, imX.shape[2],len(indices))
                """
                Data Normalisation
                """
                minValX = None
                maxValX = None
                minValY = None
                maxValY = None
                # minValX = numpy.zeros((32))
                # maxValX = numpy.ones((32))
                # minValY = numpy.zeros((32))
                # maxValY = numpy.ones((32))                
                if self.useNormData:
                    """
                    Data Normalisation
                    """
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.output_channels)
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels, minx=minValY, maxx=maxValY)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.input_channels, minx=minValX, maxx=maxValX)
                    minValX, maxValX, imX = notnormaliseFieldArray(imX, self.input_channels, minx=minValX, maxx=maxValX)
                    minValY, maxValY, imY = notnormaliseFieldArray(imY, self.output_channels, minx=minValY, maxx=maxValY)                    

                for index in itertools.islice(itertools.count(), 0, len(indices)):
                    slice_index = slice_indices[index]
                    imX_slice = numpy.squeeze(imX[:,:,slice_index,:])
                    # === we need to feed the data as 3D+1 channel data stack === #
                    if len(imX_slice.shape) < 3:
                        imX_slice = imX_slice.reshape(imX_slice.shape + (1,))
                    if len(imX_slice.shape) < 4:
                        imX_slice = imX_slice.reshape(imX_slice.shape + (1,))
                    imY_slice = numpy.squeeze(imY[:,:,slice_index,:])
                    if len(imY_slice.shape) < 3:
                        imY_slice = imY_slice.reshape(imY_slice.shape + (1,))
                    if len(imY_slice.shape) < 4:
                        imY_slice = imY_slice.reshape(imY_slice.shape + (1,))
                    # == Note: do data normalization here to reduce memory footprint ==#
                    imX_slice = imX_slice.astype(numpy.float32)
                    imY_slice = imY_slice.astype(numpy.float32)
                    with self._lock_:
                        self.cache.set_cache_item_x(indices[index],imX_slice)
                        self.cache.set_item_limits_x(indices[index], minValX, maxValX)
                        self.cache.set_cache_item_y(indices[index],imY_slice)
                        self.cache.set_item_limits_y(indices[index], minValY, maxValY)

            else:
                # === we need to feed the data as 3D+1 channel data stack === #
                if len(imX.shape) < 3:
                    imX = imX.reshape(imX.shape + (1,))
                if len(imX.shape) < 4:
                    imX = imX.reshape(imX.shape + (1,))
                if len(imY.shape) < 3:
                    imY = imY.reshape(imY.shape + (1,))
                if len(imY.shape) < 4:
                    imY = imY.reshape(imY.shape + (1,))
                # == Note: do data normalization here to reduce memory footprint ==#
                """
                Data Normalisation
                """
                minValX = None
                maxValX = None
                minValY = None
                maxValY = None
                # minValX = numpy.zeros((32))
                # maxValX = numpy.ones((32))
                # minValY = numpy.zeros((32))
                # maxValY = numpy.ones((32))                
                if self.useNormData:
                    """
                    Data Normalisation
                    """
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.output_channels)
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels, minx=minValY, maxx=maxValY)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.input_channels, minx=minValX, maxx=maxValX)
                    minValX, maxValX, imX = notnormaliseFieldArray(imX, self.input_channels, minx=minValX, maxx=maxValX)
                    minValY, maxValY, imY = notnormaliseFieldArray(imY, self.output_channels, minx=minValY, maxx=maxValY)  
                imX = imX.astype(numpy.float32)
                imY = imY.astype(numpy.float32)
                with self._lock_:
                    self.cache.set_cache_item_x(ii,imX)
                    self.cache.set_item_limits_x(ii, minValX, maxValX)
                    self.cache.set_cache_item_y(ii, imY)
                    self.cache.set_item_limits_y(ii, minValY, maxValY)

            with self._lock_:
                loadData_flag = (self.cache.is_cache_updated() == False)
        return



    def set_nsteps(self, nsteps):
        self._nsteps = nsteps

    def __len__(self):
        return self._nsteps
    #    self._nsteps = int(numpy.ceil(len(self.fileArray)/float(self.batch_size)))
    #    return int(numpy.ceil(len(self.fileArray)/float(self.batch_size)))
    
    def __getitem__(self, idx):
        self.pid = os.getpid()
        if self.seeded == False:
            numpy.random.seed(self.pid)
            self.seeded = True

        if self.useCache:
            flushCache = False
            with self._lock_:
                flushCache = (self.cache.is_cache_updated() == False)
            if flushCache == True:
                self._initCache_locked_()

        batchX = numpy.zeros(self.batch_image_size_X, dtype=numpy.float32)
        batchY = numpy.zeros(self.batch_image_size_Y, dtype=numpy.float32)
        idxArray = numpy.random.randint(0, self.cache.get_cache_size(), self.batch_size)
        for j in itertools.islice(itertools.count(),0,self.batch_size):
            imX = None
            # minValX = numpy.zeros((32))
            # maxValX = numpy.ones((32))
            minValX = None
            maxValX = None
            imY = None
            # minValY = numpy.zeros((32))
            # maxValY = numpy.ones((32))
            minValY = None
            maxValY = None
            if self.useCache:
                #imgIndex = numpy.random.randint(0, self.cache_size)
                imgIndex =idxArray[j]
                with self._lock_:
                    imX = self.cache.get_cache_item_x(imgIndex)
                    minValX, maxValX = self.cache.get_item_limits_x(imgIndex)
                    imY = self.cache.get_cache_item_y(imgIndex)
                    minValY, maxValY = self.cache.get_item_limits_y(imgIndex)
            else:
                # imgIndex = min([(idx*self.batch_size)+j, self.numImages-1,len(self.fileArray)-1])
                imgIndex = ((idx * self.batch_size) + j) % (self.numImages - 1)
                """
                Load data from disk
                """
                inName = self.fileArray[imgIndex]
                f = h5py.File(inName, 'r')
                imX = numpy.array(f['Data_X'], order='F').transpose()
                imY = numpy.array(f['Data_Y'], order='F').transpose()
                f.close()
                
                if len(imX.shape) < 3:
                    imX = imX.reshape(imX.shape + (1,))
                if len(imX.shape) < 4:
                    imX = imX.reshape(imX.shape + (1,))
                if len(imY.shape) < 3:
                    imY = imY.reshape(imY.shape + (1,))
                if len(imY.shape) < 4:
                    imY = imY.reshape(imY.shape + (1,))

                if imX.shape != imY.shape:
                    raise RuntimeError("Input- and Output sizes do not match.")
                # == Note: do data normalization here to reduce memory footprint ==#
                """
                Data Normalisation
                """
          
                if self.useNormData:
                    """
                    Data Normalisation
                    """
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.output_channels)
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels, minx=minValY, maxx=maxValY)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.input_channels, minx=minValX, maxx=maxValX)
                    minValX, maxValX, imX = notnormaliseFieldArray(imX, self.input_channels, minx=minValX, maxx=maxValX)
                    minValY, maxValY, imY = notnormaliseFieldArray(imY, self.output_channels, minx=minValY, maxx=maxValY)  
                imX = imX.astype(numpy.float32)
                imY = imY.astype(numpy.float32)

            fname_in = "img_{}_{}_{}_{}".format(self._epoch_num_, self.pid, idx, j)
            """
            Data augmentation
            """
            input_target_size = self.target_size + (self.input_channels, )
            output_target_size = self.target_size + (self.output_channels, )
            if self.useZoom:
                _zoom_factor = numpy.random.uniform(self.zoom_factor_range[0], self.zoom_factor_range[1])
                for channelIdx in itertools.islice(itertools.count(), 0, self.input_channels):
                    imX[:,:,channelIdx] = clipped_zoom(imX[:,:,channelIdx], _zoom_factor, order=3, mode='reflect')
                    imY[:,:,channelIdx] = clipped_zoom(imY[:,:,channelIdx], _zoom_factor, order=3, mode='reflect')
            if self.useResize:
                imX = transform.resize(imX, input_target_size, order=3, mode='reflect')
                imY = transform.resize(imY, output_target_size, order=3, mode='constant')
            if self.useCrop:
                imX = imX[self.im_bounds[0]:self.im_bounds[1], self.im_bounds[2]:self.im_bounds[3],:]
                imY = imY[self.im_bounds[0]:self.im_bounds[1], self.im_bounds[2]:self.im_bounds[3],:]
            if self.useFlipping:
                mode = numpy.random.randint(0,4)
                if mode == 0:   # no modification
                    pass
                if mode == 1:
                    imX = numpy.fliplr(imX)
                    imY = numpy.fliplr(imY)
                if mode == 2:
                    imX = numpy.flipud(imX)
                    imY = numpy.flipud(imY)
                if mode == 3:
                    imX = numpy.fliplr(imX)
                    imX = numpy.flipud(imX)
                    imY = numpy.fliplr(imY)
                    imY = numpy.flipud(imY)
            if self.useAWGN: # only applies to input data
                if self.input_channels > 1:
                    for channelIdx in itertools.islice(itertools.count(), 0, self.input_channels):
                        rectMin = numpy.min(imX[:,:,channelIdx])
                        rectMax = numpy.max(imX[:,:,channelIdx])
                        imX[:,:,channelIdx] = util.random_noise(imX[:,:,channelIdx], mode='gaussian', mean=self.MECTnoise_mu[channelIdx]*0.15, var=(self.MECTnoise_sigma[channelIdx]*0.15*self.MECTnoise_sigma[channelIdx]*0.15))
                        imX[:,:,channelIdx] = numpy.clip(imX[:,:,channelIdx], rectMin, rectMax)
                else:
                    rectMin = numpy.min(imX[:, :, 0])
                    rectMax = numpy.max(imX[:, :, 0])
                    imX[:, :, channelIdx] = util.random_noise(imX[:, :, 0], mode='gaussian', mean=self.SECTnoise_mu * 0.15, var=(self.SECTnoise_sigma * 0.15 * self.SECTnoise_sigma * 0.15))
                    imX[:, :, channelIdx] = numpy.clip(imX[:, :, channelIdx], rectMin, rectMax)
            if self.useMedian:
                mSize = self.medianSize[numpy.random.randint(0,len(self.medianSize))]
                if mSize > 0:
                    imX = ndimage.median_filter(imX, (mSize, mSize, 1, 1), mode='constant', cval=1.0)
                    # should the output perhaps always be median-filtered ?
                    #outImgY = ndimage.median_filter(outImgY, (mSize, mSize, 1), mode='constant', cval=1.0)
            if self.useGaussian:
                # here, it's perhaps incorrect to also smoothen the output;
                # rationale: even an overly smooth image should result is sharp outputs
                sigma = numpy.random.uniform(low=self.gaussianRange[0], high=self.gaussianRange[1])
                imX = ndimage.gaussian_filter(imX, (sigma, sigma, 0))
                #outImgY = ndimage.gaussian_filter(outImgY, (sigma, sigma, 0))
            """
            Store data if requested
            """
            if (self.save_to_dir is not None) and (self.store_img==True):
                #print("Range phantom (after scaling): {}; scale: {}; shape {}".format([numpy.min(imX), numpy.max(imX)], [min(minValX), max(maxValX)], imX.shape))
                #print("Range FBP (after scaling): {}; scale: {}; shape {}".format([numpy.min(imY), numpy.max(imY)], [min(minValY), max(maxValY)], imY.shape))
                store_imx = imX[:, :, 0, 0]
                if len(store_imx.shape) < 3:
                    store_imx = store_imx.reshape(store_imx.shape + (1,))
                sXImg = array_to_img(store_imx, data_format='channels_last')
                # save_img(os.path.join(self.save_to_dir,fname_in+"."+self.save_format),sXimg)
                sXImg.save(os.path.join(self.save_to_dir, fname_in + "_inputX." + self.save_format))
                store_imy = imY[:, :, 0, 0]
                if len(store_imy.shape) < 3:
                    store_imy = store_imy.reshape(store_imy.shape + (1,))
                sYImg = array_to_img(store_imy, data_format='channels_last')
                # save_img(os.path.join(self.save_to_dir,fname_out+"."+self.save_format), sYImg)
                sYImg.save(os.path.join(self.save_to_dir, fname_in + "_outputY." + self.save_format))
            batchX[j] = imX
            batchY[j] = imY

        # === Comment Chris: only store images on the first epoch - not on all === #
        self.store_img=False
        return batchX, batchY
    
    def on_epoch_end(self):
        self._epoch_num_ = self._epoch_num_ + 1
        # print("Epoch: {}, num. CT gens called: {}".format(self._epoch_num_, self.fan_beam_CT.getNumberOfTransformedData()))

class ScatterPhantomGenerator_inMemory(Sequence):
    
    def __init__(self, images_in,images_out, batch_size=1, image_size=(128, 128), input_channels=32, target_size=(128, 128), output_channels=1, useResize=False,
                 useCrop=False, useZoom=False, zoom_factor_range=(0.95,1.05), useAWGN = False, useMedian=False, useGaussian=False,
                 useFlipping=False, useNormData=False, save_to_dir=None, save_format="png", threadLockVar=None):
        self.batch_size = batch_size
        self.image_size = image_size
        self.target_size = target_size
        self.input_channels = input_channels
        self.output_channels = output_channels
        self.x_dtype_in = None
        self.y_dtype_in = None
        self.useResize = useResize
        self.useCrop = useCrop
        self.useAWGN = useAWGN
        self.useZoom = useZoom
        self.zoom_factor_range = zoom_factor_range
        self.useFlipping = useFlipping
        self.useMedian = useMedian
        self.medianSize = [0,1,3,5,7,9,11]
        self.useGaussian = useGaussian
        self.gaussianRange = (0, 0.075)
        self.useNormData = useNormData
        self._epoch_num_ = 0
        self.numImages = 0

        # ========================================#
        # == zoom-related image information ==#
        # ========================================#
        self.im_center = None
        self.im_shift = None
        self.im_bounds = None
        self.im_center = numpy.array([int(self.target_size[0] - 1) / 2, int(self.target_size[1] - 1) / 2], dtype=numpy.int32)
        self.im_shift = numpy.array([(self.image_size[0] - 1) / 2, (self.image_size[1] - 1) / 2], dtype=numpy.int32)
        left = max(self.im_shift[0] - self.im_center[0],0)
        right = min(left + self.target_size[0],self.image_size[0])
        top = max(self.im_shift[1] - self.im_center[1],0)
        bottom = min(top + self.target_size[1],self.image_size[1])
        self.im_bounds = (left, right, top, bottom)
        #===================================#
        #== directory-related information ==#
        #===================================#
        self.X = images_in
        self.Y = images_out
        self.numImages = self.X.shape[0]
        self.save_to_dir=save_to_dir
        self.save_format=save_format
        self.store_img = True
        self.pid = 0
        self.seeded = False
        self._lock_ = threadLockVar
        self._nsteps = int(numpy.ceil(float(len(self.X[0])) / float(self.batch_size)))
        #======================#
        #== batch size setup ==#
        #======================#
        self.batch_image_size_X = (self.batch_size, self.image_size[0], self.image_size[1], self.input_channels, 1)
        self.batch_image_size_Y = (self.batch_size, self.image_size[0], self.image_size[1], self.output_channels, 1)
        if self.useCrop or self.useResize:
            self.batch_image_size_X = (self.batch_size, self.target_size[0], self.target_size[1], self.input_channels, 1)
            self.batch_image_size_Y = (self.batch_size, self.target_size[0], self.target_size[1], self.output_channels, 1)

        ###################################
        # === actually prepare images === #
        #=================================#
        inImgDims = (self.image_size[0], self.image_size[1], self.input_channels, 1)
        outImgDims = (self.image_size[0], self.image_size[1], self.output_channels, 1)

        if (self.X.shape[0]):
            imX = self.X[0]
            self.x_dtype_in = imX.dtype
            if len(imX.shape) > 3:
                imX = numpy.squeeze(imX[:, :, :, :])
            if len(imX.shape) < 3:
                imX = imX.reshape(imX.shape + (1,))
            # === we need to feed the data as 3D+1 channel data stack === #
            if len(imX.shape) < 4:
                imX = imX.reshape(imX.shape + (1,))

            if imX.shape != inImgDims:
                print("Error - read data shape ({}) and expected data shape ({}) of X are not equal. EXITING ...".format(imX.shape, inImgDims))
                exit()

        if (self.Y.shape[0]):
            imY = self.Y[0]
            self.y_dtype_in = imY.dtype
            if len(imY.shape) > 3:
                imY = numpy.squeeze(imY[:, :, :,:])
            if len(imY.shape) < 3:
                imY = imY.reshape(imY.shape + (1,))
            # === we need to feed the data as 3D+1 channel data stack === #
            if len(imY.shape) < 4:
                imY = imY.reshape(imY.shape + (1,))

            if imY.shape != outImgDims:
                print("Error - read data shape ({}) and expected data shape ({}) of X are not equal. EXITING ...".format(imX.shape,inImgDims))
                exit()

        # ======================================== #
        # ==== crop-related image information ==== #
        # ======================================== #
        self.im_center = None
        self.im_shift = None
        self.im_bounds = None
        self.im_center = numpy.array([int(self.target_size[0] - 1) / 2, int(self.target_size[1] - 1) / 2], dtype=numpy.int32)
        self.im_shift = numpy.array([(self.image_size[0] - 1) / 2, (self.image_size[1] - 1) / 2], dtype=numpy.int32)
        left = max(self.im_shift[0] - self.im_center[0],0)
        right = min(left + self.target_size[0],self.image_size[0])
        top = max(self.im_shift[1] - self.im_center[1],0)
        bottom = min(top + self.target_size[1],self.image_size[1])
        self.im_bounds = (left, right, top, bottom)

    def set_nsteps(self, nsteps):
        self._nsteps = nsteps

    def __len__(self):
        return self._nsteps
    
    def __getitem__(self, idx):
        self.pid = os.getpid()
        if self.seeded == False:
            numpy.random.seed(self.pid)
            self.seeded = True       
        batchX = numpy.zeros((self.batch_size,self.target_size[0], self.target_size[1], self.input_channels, 1),dtype=numpy.float32)
        batchY = numpy.zeros((self.batch_size,self.target_size[0], self.target_size[1], self.output_channels, 1),dtype=numpy.float32)
        if self.useZoom:
            batchX = numpy.zeros((self.batch_size,self.target_size[0], self.target_size[1], self.input_channels, 1),dtype=numpy.float32)
            batchY = numpy.zeros((self.batch_size,self.target_size[0], self.target_size[1], self.output_channels, 1),dtype=numpy.float32)
            
        for j in itertools.islice(itertools.count(),0,self.batch_size):
            imX = None
            # minValX = numpy.zeros((32))
            # maxValX = numpy.ones((32))
            minValX = None
            maxValX = None
            imY = None
            # minValY = numpy.zeros((32))
            # maxValY = numpy.ones((32))
            minValY = None
            maxValY = None
            imgIndex = ((idx*self.batch_size)+j) % (self.numImages-1)
            #if shuffle:
            #    batchIndex = numpy.random.randint(0, min([self.numImages,len(self.fileArray)]))
            """
            Load data from memory
            """
            imX = self.X[imgIndex]
            imY = self.Y[imgIndex]
            # === we need to feed the data as 3D+1 channel data stack === #
            if len(imX.shape) < 3:
                imX = imX.reshape(imX.shape + (1,))
            if len(imX.shape) < 4:
                imX = imX.reshape(imX.shape + (1,))
            if len(imY.shape) < 3:
                imY = imY.reshape(imY.shape + (1,))
            if len(imY.shape) < 4:
                imY = imY.reshape(imY.shape + (1,))

            if imX.shape != imY.shape:
                raise RuntimeError("Input- and Output sizes do not match.")
            # == Note: do data normalization here to reduce memory footprint ==#
            """
            Data Normalisation
            """
            if self.useNormData:
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.output_channels)
                    # minValX, maxValX, imX = normaliseFieldArray(imX, self.input_channels, minx=minValY, maxx=maxValY)
                    # minValY, maxValY, imY = normaliseFieldArray(imY, self.input_channels, minx=minValX, maxx=maxValX)
                    minValX, maxValX, imX = notnormaliseFieldArray(imX, self.input_channels, minx=minValX, maxx=maxValX)
                    minValY, maxValY, imY = notnormaliseFieldArray(imY, self.output_channels, minx=minValY, maxx=maxValY)                    
            imX = imX.astype(numpy.float32)
            imY = imY.astype(numpy.float32)
            if imX.shape != imY.shape:
                raise RuntimeError("Input- and Output sizes do not match.")
            #self.image_size =outImgX.shape
            fname_in = "img_{}_{}_{}_{}".format(self._epoch_num_, self.pid, idx, j)

            """
            Data augmentation
            """
            input_target_size = self.target_size + (self.input_channels, )
            output_target_size = self.target_size + (self.output_channels, )
            if self.useZoom:
                _zoom_factor = numpy.random.uniform(self.zoom_factor_range[0], self.zoom_factor_range[1])
                for channelIdx in itertools.islice(itertools.count(), 0, self.input_channels):
                    imX[:,:,channelIdx] = clipped_zoom(imX[:,:,channelIdx], _zoom_factor, order=3, mode='reflect')
                    imY[:,:,channelIdx] = clipped_zoom(imY[:,:,channelIdx], _zoom_factor, order=3, mode='reflect')
            if self.useResize:
                imX = transform.resize(imX, input_target_size, order=3, mode='reflect')
                imY = transform.resize(imY, output_target_size, order=3, mode='constant')
            if self.useCrop:
                imX = imX[self.im_bounds[0]:self.im_bounds[1], self.im_bounds[2]:self.im_bounds[3],:]
                imY = imY[self.im_bounds[0]:self.im_bounds[1], self.im_bounds[2]:self.im_bounds[3],:]
            if self.useFlipping:
                mode = numpy.random.randint(0,4)
                if mode == 0:   # no modification
                    pass
                if mode == 1:
                    imX = numpy.fliplr(imX)
                    imY = numpy.fliplr(imY)
                if mode == 2:
                    imX = numpy.flipud(imX)
                    imY = numpy.flipud(imY)
                if mode == 3:
                    imX = numpy.fliplr(imX)
                    imX = numpy.flipud(imX)
                    imY = numpy.fliplr(imY)
                    imY = numpy.flipud(imY)
            if self.useAWGN: # only applies to input data
                if self.input_channels > 1:
                    for channelIdx in itertools.islice(itertools.count(), 0, self.input_channels):
                        rectMin = numpy.min(imX[:,:,channelIdx])
                        rectMax = numpy.max(imX[:,:,channelIdx])
                        imX[:,:,channelIdx] = util.random_noise(imX[:,:,channelIdx], mode='gaussian', mean=self.MECTnoise_mu[channelIdx]*0.15, var=(self.MECTnoise_sigma[channelIdx]*0.15*self.MECTnoise_sigma[channelIdx]*0.15))
                        imX[:,:,channelIdx] = numpy.clip(imX[:,:,channelIdx], rectMin, rectMax)
                else:
                    rectMin = numpy.min(imX[:, :, 0])
                    rectMax = numpy.max(imX[:, :, 0])
                    imX[:, :, channelIdx] = util.random_noise(imX[:, :, 0], mode='gaussian', mean=self.SECTnoise_mu * 0.15, var=(self.SECTnoise_sigma * 0.15 * self.SECTnoise_sigma * 0.15))
                    imX[:, :, channelIdx] = numpy.clip(imX[:, :, channelIdx], rectMin, rectMax)
            if self.useMedian:
                mSize = self.medianSize[numpy.random.randint(0,len(self.medianSize))]
                if mSize > 0:
                    imX = ndimage.median_filter(imX, (mSize, mSize, 1, 1), mode='constant', cval=1.0)
                    # should the output perhaps always be median-filtered ?
                    #outImgY = ndimage.median_filter(outImgY, (mSize, mSize, 1), mode='constant', cval=1.0)
            if self.useGaussian:
                # here, it's perhaps incorrect to also smoothen the output;
                # rationale: even an overly smooth image should result is sharp outputs
                sigma = numpy.random.uniform(low=self.gaussianRange[0], high=self.gaussianRange[1])
                imX = ndimage.gaussian_filter(imX, (sigma, sigma, 0))
                #outImgY = ndimage.gaussian_filter(outImgY, (sigma, sigma, 0))
            """
            Store data if requested
            """
            if (self.save_to_dir is not None) and (self.store_img==True):
                #print("Range phantom (after scaling): {}; scale: {}; shape {}".format([numpy.min(imX), numpy.max(imX)], [min(minValX), max(maxValX)], imX.shape))
                #print("Range FBP (after scaling): {}; scale: {}; shape {}".format([numpy.min(imY), numpy.max(imY)], [min(minValY), max(maxValY)], imY.shape))
                store_imx = imX[:, :, 0, 0]
                if len(store_imx.shape) < 3:
                    store_imx = store_imx.reshape(store_imx.shape + (1,))
                sXImg = array_to_img(store_imx, data_format='channels_last')
                # save_img(os.path.join(self.save_to_dir,fname_in+"."+self.save_format),sXimg)
                sXImg.save(os.path.join(self.save_to_dir, fname_in + "_inputX." + self.save_format))
                store_imy = imY[:, :, 0, 0]
                if len(store_imy.shape) < 3:
                    store_imy = store_imy.reshape(store_imy.shape + (1,))
                sYImg = array_to_img(store_imy, data_format='channels_last')
                # save_img(os.path.join(self.save_to_dir,fname_out+"."+self.save_format), sYImg)
                sYImg.save(os.path.join(self.save_to_dir, fname_in + "_outputY." + self.save_format))
            batchX[j] = imX
            batchY[j] = imY

        # === Comment Chris: only store images on the first epoch - not on all === #
        self.store_img = False
        return batchX, batchY

    def on_epoch_end(self):
        self._epoch_num_ = self._epoch_num_ + 1
        # print("Epoch: {}, num. CT gens called: {}".format(self._epoch_num_, self.fan_beam_CT.getNumberOfTransformedData()))
