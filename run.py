# Requires: Keras-1.2.1, tensorflow-0.12.1 or theano 0.8.2

import argparse

parser = argparse.ArgumentParser(description='Run nonlinear IB on MNIST dataset')
parser.add_argument('--alpha' , type=float, default=0.0, help='alpha hyperparameter value')
parser.add_argument('--engine', default='theano', choices=['tensorflow','theano'],
                    help='Deep learning engine to use (defalt: theano)')
parser.add_argument('--trainN', type=int, help='Number of training data samples')
parser.add_argument('--testN', type=int, help='Number of testing data samples')
parser.add_argument('--miN', type=int, default=1000, help='Number of training data samples to use for estimating MI')
args = parser.parse_args()

import os
if args.engine == 'theano':
    import theano
    theano.config.optimizer = 'fast_compile'
    theano.config.floatX    = 'float32'
    import os ; os.environ['KERAS_BACKEND']='theano'
else:
    import os ; os.environ['KERAS_BACKEND']='tensorflow'

import numpy as np

from collections import namedtuple
import keras
import keras.datasets.mnist
import keras.utils.np_utils
from keras.models import Sequential
from keras.layers.core import Dense
import logging    
logging.getLogger('keras').setLevel(logging.INFO)


import trainable
import reporting

mnist_mlp_base = dict( # gets 1.28-1.29 training error
    do_MI = False,
    do_validate_on_test = True,
    nbepoch             = 60,
    batch_size          = 128,
    #HIDDEN_DIMS = [800,800],
    #hidden_acts = ['relu','relu'],
    #HIDDEN_DIMS    = [800,800,256],
    HIDDEN_DIMS    = [800,800,256],
    lr_half_time   = 10,
    hidden_acts    = ['relu','relu','linear'],
    noise_logvar_grad_trainable = True,
)


opts = mnist_mlp_base.copy()
opts['do_MI'] = True

# Initialize MNIST dataset
nb_classes = 10
(X_train, y_train), (X_test, y_test) = keras.datasets.mnist.load_data()
X_train = np.reshape(X_train, [X_train.shape[0], -1]).astype('float32') / 255.
X_test  = np.reshape(X_test , [X_test.shape[0] , -1]).astype('float32') / 255.
Y_train = keras.utils.np_utils.to_categorical(y_train, nb_classes)
Y_test  = keras.utils.np_utils.to_categorical(y_test, nb_classes)


if args.trainN is not None:
    X_train = X_train[0:args.trainN]
    Y_train = Y_train[0:args.trainN]

if args.testN is not None:
    X_test = X_test[0:args.testN]
    Y_test = Y_test[0:args.testN]


Dataset = namedtuple('Dataset',['X','Y','nb_classes'])
trn = Dataset(X_train, Y_train, nb_classes)
tst = Dataset(X_test , Y_test, nb_classes)

del X_train, X_test, Y_train, Y_test, y_train, y_test
# ***************************


# Build model
model = Sequential()

for hndx, hdim in enumerate(opts['HIDDEN_DIMS']):
    cact = opts['hidden_acts'][hndx]
    if 'hidden_inits' in opts:
        cinit = opts['hidden_inits'][hndx]
    else:
        cinit = 'he_uniform' if cact == 'relu' else 'glorot_uniform'
    model.add(Dense(hdim, activation=cact, init=cinit,
                    input_dim=trn.X.shape[1] if hndx == 0 else None))
    
kdelayer, noiselayer, micomputer = None, None, None
    
cbs = [keras.callbacks.LearningRateScheduler(
        lambda epoch: 0.001 * 0.5**np.floor(epoch / opts['lr_half_time'])
    ),]

if opts.get('do_MI', True):
    mi_samples = trn.X       # input samples to use for estimating 
                             # mutual information b/w input and hidden layers
    rows = np.random.choice(mi_samples.shape[0], args.miN)
    mi_samples = mi_samples[rows,:]

    micalculator = trainable.MICalculator(model.layers[:], mi_samples, init_kde_logvar=-5.)

    noiselayer = trainable.NoiseLayer(init_logvar = -10., 
                                logvar_trainable=opts['noise_logvar_grad_trainable'],
                                test_phase_noise=opts.get('test_phase_noise', True),
                                mi_calculator=micalculator,
                                init_alpha=args.alpha)
    model.add(noiselayer)

    cbs.append(trainable.KDETrain(mi_calculator=micalculator))
    #if not opts['noise_logvar_grad_trainable']:
    #    cbs.append(miregularizer2.NoiseTrain(traindata=trn, noiselayer=noiselayer))
    cbs.append(reporting.ReportVars(noiselayer=noiselayer))

model.add(Dense(trn.nb_classes, init='glorot_uniform', activation='softmax'))

if opts.get('do_validate_on_test', False):
    validation_split = None
    validation_data = (tst.X, tst.Y)
    early_stopping = None
else:
    validation_split = 0.2
    validation_data = None
    from keras.callbacks import EarlyStopping
    cbs.append( EarlyStopping(monitor='val_loss', patience=opts['patiencelevel']) )
    
fit_args = dict(
    x          = trn.X,
    y          = trn.Y,
    verbose    = 2,
    batch_size = opts['batch_size'],
    nb_epoch   = opts['nbepoch'],
    validation_split = validation_split,
    validation_data  = validation_data,
    callbacks  = cbs,
)


optimizer = opts.get('optimizer','adam')
print "Using optimizer", optimizer
model.compile(loss='categorical_crossentropy', optimizer=optimizer, metrics=['accuracy'])

    
hist = model.fit(**fit_args)

reporting.get_logs(model, trn, tst, noiselayer, args.miN)
