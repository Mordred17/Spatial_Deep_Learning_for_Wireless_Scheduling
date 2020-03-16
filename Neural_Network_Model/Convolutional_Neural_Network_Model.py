# This repository contains our novel convolutional neural network model implementation
# for the work "Spatial Deep Learning for Wireless Scheduling", 
# available at https://ieeexplore.ieee.org/document/8664604.

# For any reproduce, further research or development, please kindly cite our JSAC journal paper:
# @Article{spatial_learn,
#    author = "W. Cui and K. Shen and W. Yu",
#    title = "Spatial Deep Learning for Wireless Scheduling",
#    journal = "{\it IEEE J. Sel. Areas Commun.}",
#    year = 2019,
#    volume = 37,
#    issue = 6,
#    pages = "1248-1261",
#    month = "June",
# }

import random
import numpy as np
import tensorflow as tf
import matplotlib.pyplot as plt
import time
import sys
sys.path.append("../Tools/")
import general_parameters
import model_parameters
import utils
import os


class Conv_Network():
    def __init__(self, general_para, batch_size):
        # Model parameters
        self.parameters = general_para
        self.N = self.parameters.n_links
        self.batch_size = batch_size # Fixed during testing time due to matrices dimension manipulation
        self.stddev_init = 0.01
        self.learning_rate = 1e-4
        self.n_grids = self.parameters.n_grids
        self.filter_size = 63
        self.n_feedback_steps = 20
        self.placeholders = dict()
        self.TFgraph = tf.Graph()
        self.model_filename = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Trained_Model", "conv_net_model.ckpt")
        print("[Convolutional Neural Network] Model path: ", self.model_filename)

    def prepare_placeholders(self):
        tx_indices_hash = tf.placeholder(tf.int64, shape=[self.batch_size * self.N, 4], name='tx_indices_placeholder')
        rx_indices_hash = tf.placeholder(tf.int64, shape=[self.batch_size * self.N, 4], name='rx_indices_placeholder')
        tx_indices_extract = tf.placeholder(tf.int32, shape=[self.batch_size, self.N, 3], name='tx_indices_extract_placeholder')  # extra index is for indicating index within the batch
        rx_indices_extract = tf.placeholder(tf.int32, shape=[self.batch_size, self.N, 3], name='rx_indices_extract_placeholder')  # extra index is for indicating index within the batch
        pair_tx_convfilter_indices = tf.placeholder(tf.int32, shape=[self.batch_size, self.N, 2], name='pair_tx_convfilter_indices_placeholder')  # for cancellating pair itself convolution contribution
        pair_rx_convfilter_indices = tf.placeholder(tf.int32, shape=[self.batch_size, self.N, 2], name='pair_rx_convfilter_indices_placeholder')  # for cancellating pair itself convolution contribution
        schedule_label = tf.placeholder(tf.float32, shape=[self.batch_size, self.N], name='scheduling_target_placeholder')
        self.placeholders['tx_indices_hash'] = tx_indices_hash
        self.placeholders['rx_indices_hash'] = rx_indices_hash
        self.placeholders['tx_indices_extract'] = tx_indices_extract
        self.placeholders['rx_indices_extract'] = rx_indices_extract
        self.placeholders['pair_tx_convfilter_indices'] = pair_tx_convfilter_indices
        self.placeholders['pair_rx_convfilter_indices'] = pair_rx_convfilter_indices
        self.placeholders['schedule_label'] = schedule_label
        # For log utility optimization
        self.placeholders['subset_links'] = tf.placeholder_with_default(input=tf.ones([self.batch_size, self.N]), shape=[self.batch_size, N], name='subset_links_placeholder')
        print("[Conv Net] Placeholder preparation finished!")
        return

    # Initialize Variables to be Reused
    def prepare_parameters(self):
        with tf.variable_scope("conv_lyr"):
            weights = tf.get_variable(name="w", shape=[self.filter_size, self.filter_size, 1, 1], initializer=tf.constant_initializer(0))
            bias = tf.get_variable(name="b", shape=[], initializer=tf.constant_initializer(-3))
            tf.add_to_collection("conv", weights)
            tf.add_to_collection("conv", bias)
        with tf.variable_scope("fc_lyr1"):
            weights = tf.get_variable(name="w", shape=[6, 30], initializer=tf.truncated_normal_initializer(stddev=self.stddev_init))
            biases = tf.get_variable(name="b", shape=[30], initializer=tf.constant_initializer(0))
            tf.add_to_collection("fc", weights)
            tf.add_to_collection("fc", biases)
        with tf.variable_scope("fc_lyr2"):
            weights = tf.get_variable(name="w", shape=[30, 30], initializer=tf.truncated_normal_initializer(stddev=self.stddev_init))
            biases = tf.get_variable(name="b", shape=[30], initializer=tf.constant_initializer(0))
            tf.add_to_collection("fc", weights)
            tf.add_to_collection("fc", biases)
        with tf.variable_scope("fc_lyr3"):
            weights = tf.get_variable(name="w", shape=[30, 1], initializer=tf.truncated_normal_initializer(stddev=self.stddev_init))
            bias = tf.get_variable(name="b", shape=[], initializer=tf.constant_initializer(0))
            tf.add_to_collection("fc", weights)
            tf.add_to_collection("fc", bias)
        print("[Conv Net] Parameters preparation finished!")
        return

    def convolution_layer(self, inputs, filters, bias):
        return tf.add(tf.nn.conv2d(inputs, filters, strides=[1, 1, 1, 1], padding="SAME"), bias)

    def fully_connected_layer(self, inputs, weights, biases):
        return tf.nn.relu(tf.add(tf.matmul(inputs, weights), biases))

    def fully_connected_layer_final(self, inputs, weights, bias):
        return tf.add(tf.matmul(inputs, weights), bias)

    def iteration_step(self, allocs_state, placeholders):
        # flatten allocs_state as grid values
        grid_values = tf.reshape(allocs_state, [self.batch_size * self.N])
        tx_grids = tf.SparseTensor(placeholders['tx_indices_hash'], grid_values, [self.batch_size, n_grids[0], n_grids[1], 1])
        tx_grids = tf.sparse_reduce_sum(tx_grids, reduction_axes=3, keepdims=True)
        rx_grids = tf.SparseTensor(placeholders['rx_indices_hash'], grid_values, [self.batch_size, n_grids[0], n_grids[1], 1])
        rx_grids = tf.sparse_reduce_sum(rx_grids, reduction_axes=3, keepdims=True)

        with tf.variable_scope("conv_lyr", reuse=True):
            weights = tf.get_variable(name="w")
            bias = tf.get_variable(name="b")
            # full region interferences
            tx_density_map_full = self.convolution_layer(tx_grids, tf.exp(weights), tf.exp(bias))
            rx_density_map_full = self.convolution_layer(rx_grids, tf.exp(weights), tf.exp(bias))
            pairing_tx_strength_full = tf.gather_nd(params=tf.squeeze(tf.exp(weights)), indices=placeholders['pair_tx_convfilter_indices'])
            pairing_rx_strength_full = tf.gather_nd(params=tf.squeeze(tf.exp(weights)), indices=placeholders['pair_rx_convfilter_indices'])
            pairing_tx_contrib_full = pairing_tx_strength_full * allocs_state
            pairing_rx_contrib_full = pairing_rx_strength_full * allocs_state

        # Select tx locations from rx convolution output, and vise versa (both shapes should be: amount_in_batch X N)
        tx_surroundings_full = tf.gather_nd(params=tf.squeeze(rx_density_map_full, axis=-1), indices=placeholders['tx_indices_extract']) - pairing_rx_contrib_full
        rx_surroundings_full = tf.gather_nd(params=tf.squeeze(tx_density_map_full, axis=-1), indices=placeholders['rx_indices_extract']) - pairing_tx_contrib_full

        direct_link_strength = pairing_tx_strength_full # amount_in_batch X N
        direct_link_strength_max = tf.tile(tf.reduce_max(direct_link_strength, axis=-1, keepdims=True),[1, N]) # amount_in_batch X N
        direct_link_strength_min = tf.tile(tf.reduce_min(direct_link_strength, axis=-1, keepdims=True),[1, N]) # amount_in_batch X N
        # Combine to obtain feature vectors
        pairs_features = tf.stack([tx_surroundings_full, rx_surroundings_full, direct_link_strength, direct_link_strength_max, direct_link_strength_min, allocs_state], axis=-1)
        with tf.variable_scope("fc_lyr1", reuse=True):
            weights = tf.get_variable(name="w")
            biases = tf.get_variable(name="b")
            pairs_features = tf.reshape(pairs_features, [-1, 6])
            fc_lyr1_outputs = self.fully_connected_layer(pairs_features, weights, biases)

        with tf.variable_scope("fc_lyr2", reuse=True):
            weights = tf.get_variable(name="w")
            bias = tf.get_variable(name="b")
            fc_lyr2_outputs = self.fully_connected_layer(fc_lyr1_outputs, weights, bias)

        with tf.variable_scope("fc_lyr3", reuse=True):
            weights = tf.get_variable(name="w")
            bias = tf.get_variable(name="b")
            fc_lyr3_outputs = self.fully_connected_layer_final(fc_lyr2_outputs, weights, bias)

        network_outputs = tf.reshape(fc_lyr3_outputs, [-1, N])

        return network_outputs  # return the current state of allocations (before taking sigmoid)


    def build_network(self):
        with self.TFgraph.as_default():
            self.get_placeholders()
            self.get_parameters() # set up parameters to be reused in iteration_step function call
            allocs_state = tf.ones(shape=[self.batch_size, N]) * placeholders['subset_links']
            for i in range(self.n_feedback_steps):
                allocs_state_logits = self.iteration_step(allocs_state, self.placeholders)
                stochastic_mask = tf.cast(tf.random_uniform(shape=[self.batch_size, N]) >= 0.5, tf.float32)
                allocs_state = allocs_state * (tf.ones([self.batch_size, N], tf.float32) - stochastic_mask) + tf.sigmoid(allocs_state_logits) * stochastic_mask
                allocs_state = allocs_state * self.placeholders['subset_links']
            self.outputs_final = tf.cast(allocs_state >= 0.5, tf.int32, name="casting_to_scheduling_output")
        print("[Conv Net] Tensorflow Graph Built Successfully!")
        return

    # Function for interpretability: start a standalone tensorflow session for convolutional filter visualization
    def plot_weights(self):
        self.build_network()
        saver = tf.train.Saver()
        with tf.Session() as sess:
            saver.restore(sess, self.model_filename)
            weights_tensorlist = tf.get_collection("conv");
            conv_weights_tensor = weights_tensorlist[0]
            assert conv_weights_tensor.name == "conv_lyr/w:0", "Tensor extraction failed, with wrong name: {}".format(conv_weights_tensor.name)
            # the weights in convolutional computation are exponentialized
            conv_weights_log_scale = sess.run(conv_weights_tensor)
        conv_weights_log_scale = np.array(conv_weights_log_scale)
        assert np.shape(conv_weights_log_scale) == (self.filter_size, self.filter_size, 1, 1), "Wrong shape: {}".format(np.shape(conv_weights_log_scale))
        plt.title("Convolutioanl Filter Weights Visualization (log scale)")
        img1 = plt.imshow(np.squeeze(conv_weights_log_scale), cmap=plt.get_cmap("Greys"), origin="lower")
        plt.colorbar(img1, cmap=plt.get_cmap("Greys"))
        plt.show()
        print("[Conv Net] Convolutional Filter Visualization Complete!")
        return





if (__name__ == '__main__'):
    import argparse
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--plot', help='Whether plotting Conv/FC weights', default=False)
    parser.add_argument('--evoIndex', help='Index for plotting allocation evolution', default=False)
    parser.add_argument('--initFC', help='Whether initialize FC parameters', default=False)
    parser.add_argument('--initMisc', help='Whether refreshing misc parameters within network', default=False)
    parser.add_argument('--initAll', help='Whether train completely from scratch', default=False)
    args = parser.parse_args()
    if (args.plot):
        print("Plotting Weights...")
        plot_weights()
        print("Plotting Finished Successfully!")
        exit(0)
    if (args.evoIndex):
        layoutIndex = int(args.evoIndex)
        print("Plotting allocation evolution on layout indexed {} in validation set...".format(layoutIndex))
        plot_allocs_evolution(layoutIndex)
        print("Plotting Finished Successfully!")
        exit(0)

    print("Loading raw data...")
    raw_data = utils.load_raw_data(general_para, model_para, ['train', 'valid'])
    train_batches_amount = round(np.shape(raw_data['train']['locations'])[0] / general_para.self.batch_size)
    valid_batches_amount = round(np.shape(raw_data['valid']['locations'])[0] / general_para.self.batch_size)
    FP_valid_active_ratio = np.mean(raw_data['valid']['FP_allocations']); FP_valid_std = np.std(raw_data['valid']['FP_allocations'])
    print("Training {} batches; Validation {} batches.".format(train_batches_amount, valid_batches_amount))

    g_train, CE, sumrate, train_step, outputs_final, placeholders = train_network()
    model_loc = general_para.base_dir + model_para.model_loc
    with g_train.as_default():
        with tf.Session() as sess:
            save_saver = tf.train.Saver()
            train_costs = []; valid_costs = []
            train_sumrates = []; valid_sumrates = []
            # Dividing and processing training/validation data
            train_batches = utils.divide_data_batches(general_para, raw_data['train'])
            train_batches = utils.add_appended_indices(general_para, train_batches)
            valid_batches = utils.divide_data_batches(general_para, raw_data['valid'])
            valid_batches = utils.add_appended_indices(general_para, valid_batches)
            if (args.initFC):
                print("Train Option: Initialize FC parameters to train from scratch...")
                load_saver = tf.train.Saver(tf.get_collection("conv"))
                print("First initialize all parameters from scratch...")
                sess.run(tf.global_variables_initializer())
                print("Restoring previously trained model conv parameters from: {}".format(model_loc))
                load_saver.restore(sess, model_loc)
            elif (args.initMisc):
                print("Train Option: Refresh Misc Parameters for Adam Optimizer...")
                conv_load_saver = tf.train.Saver(tf.get_collection("conv"))
                fc_load_saver = tf.train.Saver(tf.get_collection("fc"))
                print("First initialize all parameters from scratch...")
                sess.run(tf.global_variables_initializer())
                print("Restoring conv parameters from: {}".format(model_loc))
                conv_load_saver.restore(sess, model_loc)
                print("Restoring FC parameters from: {}".format(model_loc))
                fc_load_saver.restore(sess, model_loc)
            elif (args.initAll):
                print("Train Option: Train network completely from scratch")
                sess.run(tf.global_variables_initializer())
            else:
                print("[Train Option] Reload all parameters from {} for resume training...".format(model_loc))
                save_saver.restore(sess, model_loc)
            print("Model Parameters Preparation finished!")
            for i in range(1, general_para.epoches_amount + 1):
                print("Epoch #{}:".format(i))
                train_cost_sum = 0
                train_sumrate_sum = 0
                for j in range(train_batches_amount):
                    if (not Unsupervised_Training):
                        train_dict = {placeholders['tx_indices_hash']: train_batches['tx_indices_hash'][j],
                                      placeholders['rx_indices_hash']: train_batches['rx_indices_hash'][j],
                                      placeholders['tx_indices_extract']: train_batches['tx_indices_ext'][j],
                                      placeholders['rx_indices_extract']: train_batches['rx_indices_ext'][j],
                                      placeholders['pair_tx_convfilter_indices']:
                                          train_batches['pair_tx_convfilter_indices'][j],
                                      placeholders['pair_rx_convfilter_indices']:
                                          train_batches['pair_rx_convfilter_indices'][j],
                                      placeholders['schedule_label']: train_batches['FP_allocations'][j]}
                    else:
                        train_dict = {placeholders['tx_indices_hash']: train_batches['tx_indices_hash'][j],
                                      placeholders['rx_indices_hash']: train_batches['rx_indices_hash'][j],
                                      placeholders['tx_indices_extract']: train_batches['tx_indices_ext'][j],
                                      placeholders['rx_indices_extract']: train_batches['rx_indices_ext'][j],
                                      placeholders['pair_tx_convfilter_indices']:
                                          train_batches['pair_tx_convfilter_indices'][j],
                                      placeholders['pair_rx_convfilter_indices']:
                                          train_batches['pair_rx_convfilter_indices'][j],
                                      placeholders['schedule_label']: train_batches['FP_allocations'][j],
                                      placeholders['gains_diagonal']: train_batches['gains_diagonal'][j],
                                      placeholders['gains_nondiagonal']: train_batches['gains_nondiagonal'][j]}
                    train_cost_minibatch, train_sumrate_minibatch, _ = sess.run([CE, sumrate, train_step], feed_dict=train_dict)
                    train_cost_sum += train_cost_minibatch
                    train_sumrate_sum += train_sumrate_minibatch
                    if((j+1)%100 == 0):
                        train_costs.append(train_cost_sum/(j+1))
                        train_sumrates.append(train_sumrate_sum/(j+1))
                        # Validation
                        valid_cost_sum = 0
                        valid_sumrate_sum = 0
                        valid_allocations = []
                        for k in range(valid_batches_amount):
                            if (not Unsupervised_Training):
                                valid_dict = {placeholders['tx_indices_hash']: valid_batches['tx_indices_hash'][k],
                                              placeholders['rx_indices_hash']: valid_batches['rx_indices_hash'][k],
                                              placeholders['tx_indices_extract']: valid_batches['tx_indices_ext'][k],
                                              placeholders['rx_indices_extract']: valid_batches['rx_indices_ext'][k],
                                              placeholders['pair_tx_convfilter_indices']: valid_batches['pair_tx_convfilter_indices'][k],
                                              placeholders['pair_rx_convfilter_indices']: valid_batches['pair_rx_convfilter_indices'][k],
                                              placeholders['schedule_label']: valid_batches['FP_allocations'][k]}
                            else:
                                valid_dict = {placeholders['tx_indices_hash']: valid_batches['tx_indices_hash'][k],
                                              placeholders['rx_indices_hash']: valid_batches['rx_indices_hash'][k],
                                              placeholders['tx_indices_extract']: valid_batches['tx_indices_ext'][k],
                                              placeholders['rx_indices_extract']: valid_batches['rx_indices_ext'][k],
                                              placeholders['pair_tx_convfilter_indices']: valid_batches['pair_tx_convfilter_indices'][k],
                                              placeholders['pair_rx_convfilter_indices']: valid_batches['pair_rx_convfilter_indices'][k],
                                              placeholders['schedule_label']: valid_batches['FP_allocations'][k],
                                              placeholders['gains_diagonal']: valid_batches['gains_diagonal'][k],
                                              placeholders['gains_nondiagonal']: valid_batches['gains_nondiagonal'][k]}
                            valid_cost_minibatch, valid_sumrate_minibatch, valid_allocations_batch = sess.run([CE, sumrate, outputs_final], feed_dict=valid_dict)
                            valid_cost_sum += valid_cost_minibatch
                            valid_sumrate_sum += valid_sumrate_minibatch
                            valid_allocations.append(valid_allocations_batch)
                        valid_costs.append(valid_cost_sum/valid_batches_amount)
                        valid_sumrates.append(valid_sumrate_sum/valid_batches_amount)
                        print("Minibatch #{}/{} [T] avg cost: {} | [V] avg cost: {}".format(j + 1, train_batches_amount,
                                                                                            round(train_costs[-1], 3),
                                                                                            round(valid_costs[-1], 3)))
                        print("                 [V] net active ratio: {}% | FP active ratio: {}%".format(
                            round(np.mean(valid_allocations) * 100, 2), round(FP_valid_active_ratio * 100, 2)))
                        print(
                            "                 [V] net std: {} | FP std: {}".format(round(np.std(valid_allocations), 2),
                                                                                   round(FP_valid_std, 2)))
                        if (Unsupervised_Training):
                            print("                 [T] sum rate: {} | [V] sum rate: {}".format(train_sumrates[-1],
                                                                                                valid_sumrates[-1]))
                        np.save("train_costs.npy", train_costs)
                        np.save("valid_costs.npy", valid_costs)
                        np.save("train_sumrates.npy", train_sumrates)
                        np.save("valid_sumrates.npy", valid_sumrates)
                        save_path = save_saver.save(sess, model_loc)
                        print("Model saved at {}!".format(save_path))
            # Finished training, save model
            print("Training iterations finished, saving model...")
            save_path = save_saver.save(sess, model_loc)
            print("Model saved at {}!".format(save_path))
    print("Training Session finished successfully!")

    print("Script Finished Successfully!")