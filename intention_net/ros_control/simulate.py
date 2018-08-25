"""
simulate rostopics from dataset for testing
"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import fire
import numpy as np
from tqdm import tqdm

# ros packages
import rospy
from std_msgs.msg import Float32, Int32
from sensor_msgs.msg import Image
from geometry_msgs.msg import Twist
import cv2
from cv_bridge import CvBridge

# import local file
from policy import Policy


def plot_wrapper(dataset, data_dir, mode, model_dir, num_intentions=5):
    if dataset == 'CARLA':
        from intention_net.dataset import CarlaImageDataset as Dataset
        print ('=> use CARLA published data')
    elif dataset == 'CARLA_SIM':
        from intention_net.dataset import CarlaSimDataset as Dataset
        print ('=> use CARLA self-collected data')
    else:
        from intention_net.dataset import HuaWeiFinalDataset as Dataset
        print ('=> use HUAWEI data')

    sim_loader = Dataset(data_dir, 1, num_intentions, mode, preprocess=False)
    policy = Policy(mode, 2, model_dir, num_intentions)
    ground_truth = []
    pred_control = []
    speeds = []
    for step, (x, y) in enumerate(tqdm(sim_loader)):
        if (step == len(sim_loader)):
            break
        img = x[0][0].astype(np.uint8)
        intention = x[1][0]
        if mode == 'DLM':
            intention = np.argmax(intention)
        else:
            intention = intention.astype(np.uint8)
        speed = x[2][0, 0]
        control = y[0]
        pred = policy.predict_control(img, intention, speed)[0]
        # add data for plot
        ground_truth.append(control)
        pred_control.append(pred)
        speeds.append(speed)
    # change to numpy array
    ground_truth = np.array(ground_truth)
    pred_control = np.array(pred_control)
    speeds = np.array(speeds)

    # plot
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, sharey=True)
    x = np.arange(len(sim_loader))
    ax1.plot(x, ground_truth[:,0], 'k', lw=4)
    ax1.plot(x, pred_control[:,0], 'r', lw=4)
    ax2.plot(x, ground_truth[:,1], 'k--', lw=4)
    ax2.plot(x, pred_control[:,1], 'r--', lw=4)
    ax1.plot(x, speeds, 'g', lw=4)
    ax2.plot(x, speeds, 'g', lw=4)
    fig.suptitle(mode, fontsize="x-large")
    ax1.set_xlabel('Time')
    ax2.set_xlabel('Time')
    ax1.set_ylabel('Steer')
    ax2.set_ylabel('Acceleration')
    plt.show()

def main_wrapper(dataset, data_dir, num_intentions=5, mode='DLM'):
    if dataset == 'CARLA':
        from intention_net.dataset import CarlaImageDataset as Dataset
        print ('=> use CARLA published data')
    elif dataset == 'CARLA_SIM':
        from intention_net.dataset import CarlaSimDataset as Dataset
        print ('=> use CARLA self-collected data')
    else:
        from intention_net.dataset import HuaWeiFinalDataset as Dataset
        print ('=> use HUAWEI data')

    # create rosnode
    rospy.init_node('simulate')
    # only for debug so make it slow
    rate = rospy.Rate(5)
    rgb_pub = rospy.Publisher('/image', Image, queue_size=1)
    speed_pub = rospy.Publisher('/speed', Float32, queue_size=1)
    control_pub = rospy.Publisher('/labeled_control', Twist, queue_size=1)
    if mode == 'DLM':
        intention_pub = rospy.Publisher('/intention', Int32, queue_size=1)
    else:
        intention_pub = rospy.Publisher('/intention', Image, queue_size=1)

    sim_loader = Dataset(data_dir, 1, num_intentions, mode, preprocess=False)
    for step, (x, y) in enumerate(tqdm(sim_loader)):
        img = x[0][0].astype(np.uint8)
        img = CvBridge().cv2_to_imgmsg(img, encoding='bgr8')
        intention = x[1][0]
        if mode == 'DLM':
            intention = np.argmax(intention)
        else:
            intention = intention.astype(np.uint8)
            intention = CvBridge().cv2_to_imgmsg(intention, encoding='bgr8')
        speed = x[2][0, 0]
        control = y[0]
        twist = Twist()
        twist.linear.x = control[1]
        twist.angular.z = control[0]
        # publish topics
        rgb_pub.publish(img)
        intention_pub.publish(intention)
        speed_pub.publish(speed)
        control_pub.publish(twist)
        rate.sleep()

def main():
    fire.Fire({
        'plot': plot_wrapper,
        'ros': main_wrapper,
    })
    
if __name__ == '__main__':
    main()