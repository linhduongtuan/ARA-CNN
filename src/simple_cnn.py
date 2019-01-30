#!/usr/bin/env python

import os
import shutil

from keras.callbacks import ModelCheckpoint, ReduceLROnPlateau, TensorBoard, Callback
from keras.layers import (Input, GlobalAveragePooling2D, add, AveragePooling2D,
                          Dense, Dropout)
from keras.layers.advanced_activations import LeakyReLU
from keras.models import Model, load_model
from keras.preprocessing.image import ImageDataGenerator
from keras.regularizers import l2
from matplotlib import pyplot as plt
from model_utils import import_folder_to_numpy_array, single_class_accuracy, build_stem_cnn_block, get_dataset_path
from config import CLASS_DICT, CHANNELS, COLOR_TYPE, IMAGE_SIZE, DEFAULT_OPTIMIZER
import logging


logger = logging.getLogger()
logger.setLevel(logging.DEBUG)


def build_simple_cnn_model_with_dropout(
        input_size=None,
        dropout_layer=32,
        dropout_rate=0.5,
        nb_of_residual_blocks_in_first_path=4,
        nb_of_residual_blocks_in_second_path=3,
        freeze_batch=False):
    """
    This function builds a simple model with dropout.
    :param input_size: A size of the input image (default None - then default values are provided).
    :param dropout_layer: A number of filters in dropout layer.
    :param dropout_rate: A rate of dropout.
    :param nb_of_residual_blocks_in_first_path: Number of residual blocks in a first path.
    :param nb_of_residual_blocks_in_second_path: Number of residual blocks in a second path.
    :param freeze_batch: Flag if Batch normalization should be freezed while Variational inference.
    :return: A compiled model.
    """
    if input_size is None:
        input_size = (IMAGE_SIZE[0], IMAGE_SIZE[1], CHANNELS)

    input_tensor = Input(shape=input_size)

    acc_tensor = input_tensor
    # Stem part
    acc_tensor = build_stem_cnn_block(
        input_tensor_=acc_tensor,
        filter_nb=64,
        filter_size=(7, 7),
        strides=(4, 4),
        pooling_size=(2, 2),
        freeze_batch=freeze_batch,)

    # First residual block
    for _ in range(nb_of_residual_blocks_in_first_path):
        acc_tensor = create_residual_block(
            freeze_batch=freeze_batch,
            pooling=False)(acc_tensor)

    acc_tensor = AveragePooling2D()(acc_tensor)

    aux_output = create_dropout_output(
        dropout_layer=dropout_layer,
        dropout_rate=dropout_rate,
        output_name='aux_output')(acc_tensor)

    # Second residual block
    for _ in range(nb_of_residual_blocks_in_second_path):
        acc_tensor = create_residual_block(
            freeze_batch=freeze_batch,
            pooling=False)(acc_tensor)

    acc_tensor = AveragePooling2D()(acc_tensor)

    main_output = create_dropout_output(
        dropout_layer=dropout_layer,
        dropout_rate=dropout_rate,
        output_name='main_output')(acc_tensor)

    simple_model_with_dropout = Model(input_tensor, [main_output, aux_output])

    simple_model_with_dropout.compile(
        optimizer=DEFAULT_OPTIMIZER,
        loss="sparse_categorical_crossentropy",
        loss_weights={"main_output": 0.9, "aux_output": 0.1},
        metrics=["acc", single_class_accuracy(0)])

    return simple_model_with_dropout


def create_dropout_output(dropout_layer, dropout_rate, output_name):
    """
    This function creates an output from a model.
    :param dropout_layer: Size of filters in dropout layer.
    :param dropout_rate: A rate of dropout ratio.
    :param output_name: A name of output tensor.
    :return: An output layer.
    """
    def _dropout_output(acc_tensor):
        output = GlobalAveragePooling2D()(acc_tensor)
        output = Dense(
            dropout_layer,
            kernel_regularizer=l2(0.0001), )(output)
        output = LeakyReLU(alpha=0.1)(output)
        output = Dropout(dropout_rate)(output)
        output = Dense(8, activation="softmax", name=output_name)(output)
        return output
    return _dropout_output


def create_output(output_name):
    """
    This function creates an output from a model.
    :param output_name: A name of output tensor.
    :return: An output layer.
    """
    def _output(acc_tensor):
        output = GlobalAveragePooling2D()(acc_tensor)
        output = Dense(8, activation="softmax", name=output_name)(output)
        return output
    return _output


def create_residual_block(pooling, freeze_batch=False, filter_nb=64, filter_size=(3, 3)):
    """
    This function creates a residual block.
    :param freeze_batch: Flag if Batch normalization should be freezed at variational inference time.
    :param pooling: Flag if pooling should be applied.
    :param filter_nb: Number of filters.
    :param filter_size: A size of filters.
    :return: A residual block layer.
    """
    def _block(acc_tensor):
        residual_tensor = build_stem_cnn_block(
            input_tensor_=acc_tensor,
            filter_nb=filter_nb,
            filter_size=filter_size,
            freeze_batch=freeze_batch,
            pooling=pooling,)
        acc_tensor = add([acc_tensor, residual_tensor])
        return acc_tensor
    return _block


def build_simple_cnn_model(
        input_size=None,
        nb_of_residual_blocks_in_first_path=4,
        nb_of_residual_blocks_in_second_path=4,):

    if input_size is None:
        input_size = (IMAGE_SIZE[0], IMAGE_SIZE[1], CHANNELS)

    input_tensor = Input(shape=input_size)

    acc_tensor = input_tensor
    # Stem part
    acc_tensor = build_stem_cnn_block(
        input_tensor_=acc_tensor,
        filter_nb=64,
        filter_size=(7, 7),
        strides=(4, 4),
        pooling_size=(2, 2),)

    # First residual block
    for _ in range(nb_of_residual_blocks_in_first_path):
        acc_tensor = create_residual_block(
            pooling=False)(acc_tensor)

    acc_tensor = AveragePooling2D()(acc_tensor)

    aux_output = create_output(
        output_name='aux_output')(acc_tensor)

    # Second residual block
    for _ in range(nb_of_residual_blocks_in_second_path):
        acc_tensor = create_residual_block(
            pooling=False)(acc_tensor)

    acc_tensor = AveragePooling2D()(acc_tensor)

    main_output = create_output(
        output_name='main_output')(acc_tensor)
    simple_model = Model(input_tensor, [main_output, aux_output])

    simple_model.compile(optimizer=DEFAULT_OPTIMIZER,
                         loss="sparse_categorical_crossentropy",
                         loss_weights={"main_output": 0.9, "aux_output": 0.1},
                         metrics=["acc", single_class_accuracy(0)])

    return simple_model


def multioutput_gen(gen, nb_of_outputs=2):
    """
    A helper function which duplicates
    :param gen:
    :param nb_of_outputs:
    :return:
    """
    for x, y in gen:
        yield x, [y] * nb_of_outputs


class RestartCallback(Callback):
    def __init__(self, check_epoch_nb, monitor, value):
        super(RestartCallback, self).__init__()
        self.check_epoch_nb = check_epoch_nb
        self.monitor = monitor
        self.value = value
        self.stopped = False

    def on_train_begin(self, logs=None):
        self.stopped = False

    def on_epoch_end(self, epoch, logs=None):
        logger.debug(epoch, logs.get(self.monitor), self.value)
        if (epoch + 1) != self.check_epoch_nb:
            return

        if logs.get(self.monitor) <= self.value:
            return

        logger.debug("Restarting training.")
        self.model.stop_training = True
        self.stopped = True


def train_cycle(train_path, step, output_dir):
    THRESHOLD_LOSS_VALUE_1 = 2.0
    THRESHOLD_LOSS_VALUE_2 = 0.8
    RESTARTER_PATIENCE_1 = 10
    RESTARTER_PATIENCE_2 = 100
    TRAIN_BATCH_SIZE = 32
    TEST_BATCH_SIZE = 128
    SEED = 42
    EPOCHS = 100

    test_path = get_dataset_path("test")

    base_generator = ImageDataGenerator(rescale=1.0 / 255,
                                        horizontal_flip=True,
                                        vertical_flip=True,
                                        rotation_range=90,
                                        zoom_range=0.4,
                                        width_shift_range=0.1,
                                        height_shift_range=0.1)

    base_valid_generator = ImageDataGenerator(rescale=1.0/255)

    train_x, train_y = import_folder_to_numpy_array(
        folder_path=train_path,
        target_size=IMAGE_SIZE,
        color_mode=COLOR_TYPE,
        class_dict=CLASS_DICT
    )

    test_x, test_y = import_folder_to_numpy_array(
        folder_path=test_path,
        target_size=IMAGE_SIZE,
        color_mode=COLOR_TYPE,
        class_dict=CLASS_DICT
    )

    import math

    label_indices = {}
    for i in range(0, train_y.shape[0]):
        if not train_y[i] in label_indices:
            label_indices[train_y[i]] = []

        label_indices[train_y[i]].append(i)

    train_indices = []
    val_indices = []
    for key, value in label_indices.items():
        train_size = math.floor(0.7 * len(value))
        for index1 in value[:train_size]:
            train_indices.append(index1)
        for index2 in value[train_size:]:
            val_indices.append(index2)

    valid_x = train_x[val_indices]
    valid_y = train_y[val_indices]
    train_x = train_x[train_indices]
    train_y = train_y[train_indices]
    
    train_generator = base_generator.flow(train_x, train_y, batch_size=TRAIN_BATCH_SIZE, seed=SEED)
    valid_generator = base_valid_generator.flow(valid_x, valid_y, batch_size=TEST_BATCH_SIZE, seed=SEED)
    test_generator = base_valid_generator.flow(test_x, test_y, batch_size=TEST_BATCH_SIZE, seed=SEED)

    experiment_name = "extended_model_" + str(step)

    tensorboard = TensorBoard()
    checkpointer = ModelCheckpoint(filepath=output_dir + "/" + experiment_name + ".h5")
    reducer = ReduceLROnPlateau(monitor="val_main_output_acc", verbose=1)

    restarter_1 = RestartCallback(
        check_epoch_nb=RESTARTER_PATIENCE_1,
        monitor="main_output_loss",
        value=THRESHOLD_LOSS_VALUE_1, )

    restarter_2 = RestartCallback(
        check_epoch_nb=RESTARTER_PATIENCE_2,
        monitor="main_output_loss",
        value=THRESHOLD_LOSS_VALUE_2, )

    class_weights = {0: 5,
                     1: 1,
                     2: 1,
                     3: 1,
                     4: 1,
                     5: 1,
                     6: 1,
                     7: 1}

    while True:
        model = build_simple_cnn_model_with_dropout()
        history = model.fit_generator(multioutput_gen(train_generator),
                                      steps_per_epoch=int(train_x.shape[0] / TRAIN_BATCH_SIZE),
                                      epochs=EPOCHS,
                                      validation_data=multioutput_gen(valid_generator),
                                      validation_steps=int(math.ceil(valid_x.shape[0] / TEST_BATCH_SIZE)),
                                      class_weight=class_weights,
                                      callbacks=[checkpointer, reducer, tensorboard, restarter_1, restarter_2],
                                      verbose=1)
        if not restarter_1.stopped or restarter_2.stopped:
            break

    eval_result = model.evaluate_generator(multioutput_gen(test_generator),
                                           steps=int(test_x.shape[0] / TEST_BATCH_SIZE))

    with open(output_dir + "/" + experiment_name + ".txt", "w") as dst:
        for epoch_nb in range(len(history.history["loss"])):
            dst.write("%d, %f, %f, %f, %f, %f, %f, %f, %f, %f, %f, %f, %f\n" % (
                epoch_nb + 1,
                history.history["loss"][epoch_nb],
                history.history["main_output_loss"][epoch_nb],
                history.history["aux_output_loss"][epoch_nb],
                history.history["main_output_acc"][epoch_nb],
                history.history["aux_output_acc"][epoch_nb],
                history.history["val_loss"][epoch_nb],
                history.history["val_main_output_loss"][epoch_nb],
                history.history["val_aux_output_loss"][epoch_nb],
                history.history["val_main_output_acc"][epoch_nb],
                history.history["val_aux_output_acc"][epoch_nb],
                eval_result[3], #eval_main_acc
                eval_result[5])) #eval_aux_acc
