from __future__ import print_function

import sys,os,glob
sys.path.append('/home/jakub/projects/deep_learning_art_webinar')

import time

import numpy as np

from matplotlib import pylab as plt
from PIL import Image

from scipy.optimize import fmin_l_bfgs_b

from keras.applications.vgg16 import VGG16
from keras.applications.imagenet_utils import preprocess_input,decode_predictions
from keras.preprocessing import image as img_utils
from keras.layers import Input
import keras.backend as K

import utils

# NEPTUNE CONFIG

ctx = neptune.Context()

logging_channel = ctx.job.create_channel(
    name='logging_channel',
    channel_type=neptune.ChannelType.TEXT)

loss_channel = ctx.job.create_channel(
    name='training loss',
    channel_type=neptune.ChannelType.NUMERIC)

result_channel = ctx.job.create_channel(
    name='result image',
    channel_type=neptune.ChannelType.IMAGE)

ctx.job.register_action(name='set layer number', handler = set_layer_nr)
ctx.job.register_action(name='set filter number', handler = set_filter_nr)
ctx.job.register_action(name='set coefficient', handler = set_coeff)
ctx.job.register_action(name='set jitter', handler = set_jitter)

def set_layer_nr(value):
    global FILTER_NR
    FILTER_NR  = int(value)
    return str(FILTER_NR)
    
def set_filter_nr(value):
    global FILTER_NR
    FILTER_NR  = int(value)
    return str(FILTER_NR)

def set_coeff(value):
    global COEFF
    COEFF  = float(value)
    return str(COEFF)
    
def set_jitter(value):
    global JITTER
    JITTER  = int(value)
    return str(JITTER)

# GLOBALS
BASE_IMAGE_PATH = (ctx.params.base_file)
DREAM_ITER = (ctx.params.dream_iter)
LAYER_NR = (ctx.params.layer_nr)
FILTER_NR = (ctx.params.filter_nr)
COEFF = (ctx.params.coeff)
JITTER = (ctx.params.jitter)

# this will contain our generated image
img_size = (224, 224, 3)
input_template = Input(batch_shape=(1,) + img_size)

img_recognition_network = VGG16(input_tensor=input_template, 
                                weights='imagenet', 
                                include_top=True)

layer_dict = utils.get_layer_dict(img_recognition_network)

def neptune_image(raw_image,description):
    stylish_image = Image.fromarray(raw_image)
    return neptune.Image(
        name="neptune dreams",
        description=description,
        data=stylish_image)

BASE_IMAGE_PATH = (ctx.params.base_file)
DREAM_ITER = (ctx.params.dream_iter)
LAYER_NR = (ctx.params.layer_nr)
FILTER_NR = (ctx.params.filter_nr)
COEFF = (ctx.params.coeff)
JITTER = (ctx.params.jitter)

def eval_loss_and_grads(img_tensor,layer_dict,
                       layer_type,layer_nr,filter_nr,coeff):
 
    x = layer_dict[layer_nr].output[:,:,:,filter_nr]

    loss =  - coeff * K.sum(K.square(x))

    grads = K.gradients(loss, input_template)

    grad_loss_func = K.function([input_template], [loss] + grads)
    
    img_tensor = img_tensor.reshape((1,)+img_size)
    
    outs = grad_loss_func([img_tensor])

    loss_value = outs[0]
    grad_values = outs[1].flatten().astype('float64')

    return loss_value, grad_values


class Evaluator(object):
    def __init__(self,layer_dict,layer_nr,filter_nr,coeff):
        self.loss_value = None
        self.grad_values = None
        self.layer_dict = layer_dict
        self.layer_nr = layer_nr
        self.filter_nr = filter_nr
        self.coeff = coeff

    def loss(self, x):
        assert self.loss_value is None
        loss_value, grad_values = eval_loss_and_grads(x,
                                                      self.layer_dict,
                                                      self.layer_nr,
                                                      self.filter_nr,
                                                      self.coeff)
        self.loss_value = loss_value
        self.grad_values = grad_values
        return self.loss_value

    def grads(self, x):
        assert self.loss_value is not None
        grad_values = np.copy(self.grad_values)
        self.loss_value = None
        self.grad_values = None
        return grad_values


if __name__ == "__main__":

    img_dream = img_utils.load_img(BASE_IMAGE_PATH,target_size = img_size[:2])
    x = utils.img2vggtensor(img_dream) 

    for i in range(DREAM_ITER):
        
        evaluator = Evaluator(layer_dict = layer_dict,
                              layer_nr = layer_nr,filter_nr = filter_nr,
                              coeff = coeff)
        
        logging_channel.send(x = time.time(),y = "iteration %s start"%i)

        random_jitter = (JITTER * 2) * (np.random.random(img_size) - 0.5)
        x += random_jitter

        x, min_val, info = fmin_l_bfgs_b(evaluator.loss, x.flatten(),
                                         fprime=evaluator.grads, maxfun=7)
        loss_channel.send(x = i, y = float(min_val))
        logging_channel.send(x = time.time(),y = "iteration %s error %s"%(i,min_val))

        x = x.reshape((1,)+img_size)
        x -= random_jitter
        img = utils.deprocess_image(np.copy(x))
        
        description = "img_{}_{}_{}_{}_{}".\
                                format(LAYER_NR,
                                       FILTER_NR,
                                       COEFF,
                                       JITTER,
                                       i
                                      )
            
        result_channel.send(x = time.time(),
                            y = neptune_img(img,description)
                            )