# Copyright 2018 Daniel Hernandez Diaz, Columbia University
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# ==============================================================================
import abc
import pickle
import os
from abc import abstractmethod

import numpy as np
import tensorflow as tf

from neurolib.utils.graphs import get_session

# pylint: disable=bad-indentation, no-member, protected-access

class Model(abc.ABC):
  """
  An abstract class for Machine Learning Models.
  
  Classes that inherit from the abstract class Model will be seen by the client.
  Models are created through a Builder object, which in turn is endowed with an
  interface via which the client may add Nodes and Links to the Model as
  desired.
  
  There are two ways of invoking a Model.
  
  a) Default
    An instance of Model is created using a set of mandatory directives specific
    to the Model as in
      model = Model(*args, **dirs)
    Some control over the model hyperparameters is provided through the
    directives `**dirs`. The Model Builder object is automatically created.
    
  b) Custom
    The instance of Model is created through a custom Builder object
      model = Model(builder=mybuilder)
    where the custom builder object is used to declare the graphical model as
    desired by the user. This provides a lot more control over the model
    hyperparameters since each node of the Model graph can be independently
    tweaked.
    
  The Model classes should implement at the very least the following methods
  
  train(...)
  sample(...)
  """
  def __init__(self):
    """
    TODO: Should I start a session here? This presents some troubles right now,
    at least with this implementation of get_session which I am beginning to
    suspect it is not going to cut it for our purposes. The sessions needs to be
    micromanaged...
    
    TODO: I also want to manually manage the graphs for when people want to run
    two models and compare for example. Although, a comparison is naturally
    external to each model. I think that what I want to do in fact is produce plo
    """
#     self.inputs = {}
#     self.outputs = {}
    tf.reset_default_graph()
    self.sess = tf.Session()
    
    self._is_built = False
    
  @property
  def main_scope(self):
    """
    """
    return self._main_scope
      
  @abstractmethod
  def build(self):
    """
    """
    raise NotImplementedError("")
        
  def update(self, dataset):
    """
    Carry a single update on the model  
    """
    self.trainer.update(dataset)

  @abstractmethod
  def train(self, dataset, num_epochs, **dirs):
    """
    """
    raise NotImplementedError("")

  def prepare_dataset(self, dataset):
    """
    """
    scope = self.main_scope
    dset = {}
    for key in dataset:
      dset[scope + '/' + key + '_main:0'] = dataset[key]
    return dset
      
  def prepare_datasets(self, dataset):
    """
    Split the dataset dictionary into train, validation and test datasets.
    """
    scope = self.main_scope
    train_dataset = {}
    valid_dataset = {}
    test_dataset = {}
    for key in dataset:
      d_set, inode = key.split('_')[0], "_".join(key.split('_')[1:])
      if d_set == 'train':
        train_dataset[scope + '/' + inode + '_main:0'] = dataset[key]
      elif d_set == 'valid':
        valid_dataset[scope + '/' + inode + '_main:0'] = dataset[key]
      elif d_set == 'test':
        test_dataset[scope + '/' + inode + '_main:0'] = dataset[key]
      else:
        raise KeyError("The dataset contains the key `{}`. The only allowed "
                       "prefixes for keys in the dataset are 'train', "
                       "'valid' and 'test'".format(key))
    
    return {'train' : train_dataset,
            'valid' : valid_dataset, 
            'test' : test_dataset}
    
  def batch_iterator_from_dataset(self, dataset, shuffle=True):
    """
    """
    nsamps = len(list(dataset.values())[0])
    l_inds = np.arange(nsamps)
    if shuffle:
      np.random.shuffle(l_inds)
    for idx in range(nsamps//self.batch_size):
      yield {key : value[l_inds[idx:idx+self.batch_size]] for key, value
             in dataset.items()}

  def reduce_op_from_batches(self,
                             sess,
                             op,
                             dataset,
                             reduction='mean',
                             num_batches=100):
    """
    Reduce op from batches
    """
    if self.batch_size is None:
      return sess.run(op, feed_dict=dataset)
    else:
      reduced = 0
      dataset_iter = self.batch_iterator_from_dataset(dataset)
      if reduction == 'mean' or reduction == 'sum':
        for batch_data in dataset_iter:
          reduced += sess.run(op, feed_dict=batch_data)[0]
        if reduction == 'mean': return reduced/(self.batch_size*num_batches)
        else: return reduced
          
  def sample(self, input_data, node, islot=0):
    """
    Sample from the model graph. For user provided features generates a
    response.
    """
    addcolon0 = lambda s : self.main_scope +  '/' + s + ':0'
    node = self.nodes[node]
    sess = get_session()
    input_data = {addcolon0(key) : value for key, value in input_data.items()}
    if self.batch_size is None:
      return sess.run(node._islot_to_itensor[islot], feed_dict=input_data)
    else:
      num_samples =len(list(input_data.values())[0]) 
      if num_samples % self.batch_size:
        raise ValueError("The number of samples ({})is not divisible by "
                         "self.batch_size({})".format(num_samples,
                                                      self.batch_size))
      res = np.zeros([num_samples] + node._islot_to_shape[islot][1:])
      i = 0
      for batch_data in self.batch_iterator_from_dataset(input_data,
                                                         shuffle=False):
        r = sess.run(node._islot_to_itensor[islot],
                     feed_dict=batch_data)
        res[i:i+self.batch_size] = r
        i += 1
      return res
  
  def extract_dirs(self, prefix):
    """
    Make a new dictionary with directives matching a prefix
    """
    return {'_'.join(key.split('_')[1:]) : value for key, value 
            in self.directives.items() if key.startswith(prefix)}
    
  @staticmethod
  def get_latest_metafile_in_rslt_dir(rslt_dir):
    """
    Return the latest metafile in the provided directory
    """
    prefixes = [file[:-5] for file in os.listdir(rslt_dir) if 'meta'==file.split('.')[-1]]
    return max([f for f in prefixes], key=lambda f : int(f.split('-')[-1])) + '.meta'

  def _restore(self, metafile=None):
    """
    Restore a saved model 
    """
    rslt_dir = self.rslt_dir
    if metafile is None:
      metafile = self.get_latest_metafile_in_rslt_dir(rslt_dir)
      print("... from metafile {}".format(metafile))
      saver = tf.train.import_meta_graph(rslt_dir+metafile)
    else:
      saver = tf.train.import_meta_graph(rslt_dir+metafile)
    
    saver.restore(self.sess, tf.train.latest_checkpoint(rslt_dir))
    self.sess.run(tf.global_variables_initializer())

  def save_otensor_names(self):
    """
    Store a user friendly hash to whose values are the names of the output
    tensors of every node
    """
    rslt_dir = self.trainer.rslt_dir
    with open(rslt_dir + 'output_names', 'wb') as f1:
      print("self.builder.otensor_names", self.builder.otensor_names)
      pickle.dump(self.otensor_names, f1)
    
    return self.otensor_names

  def eval(self, names, dataset, key=None):
    """
    Evaluate an op given an input dataset.
    """
    sess = self.sess
    if isinstance(names, str): names = [names]
    opnames = [self.ops_names[name] for name in names]
    
    if key is None:
      fd = self.prepare_dataset(dataset)
    else:
      dataset_dict = self.prepare_datasets(dataset)
      fd = dataset_dict[key]
    
    return sess.run(opnames, feed_dict=fd)
