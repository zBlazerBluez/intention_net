"""
Run the learned model to connect to client with ros messages
"""
import pygame
import time
import sys
import fire
import string 
import random

# import local file
from joy_teleop import JOY_MAPPING
from policy import Policy
# ros packages
import rospy
from sensor_msgs.msg import Joy, Image, Imu, CompressedImage
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32, Float32, String
from nav_msgs.msg import Odometry
import cv2
from cv_bridge import CvBridge
from intention_net.dataset import PioneerDataset as Dataset

# SCREEN SCALE IS FOR high dpi screen, i.e. 4K screen
SCREEN_SCALE = 1
WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 768
INTENTION = {
    0: 'STRAIGHT_FORWARD',
    1: 'STRAIGHT_BACK',
    2: 'LEFT_TURN',
    3: 'RIGHT_TURN',
    4: 'LANE_FOLLOW',
}

class Timer(object):
    def __init__(self):
        self.step = 0
        self._lap_step = 0
        self._lap_time = time.time()

    def tick(self):
        self.step += 1

    def lap(self):
        self._lap_step = self.step
        self._lap_time = time.time()

    def ticks_per_second(self):
        return float(self.step - self._lap_step) / self.elapsed_seconds_since_lap()

    def elapsed_seconds_since_lap(self):
        return time.time() - self._lap_time

class Controller(object):
    tele_twist = Twist()
    def __init__(self, mode, scale_x, scale_z, rate):
        global INTENTION
        self.INTENTION_MAPPING = INTENTION
        self._mode = mode
        self._scale_x = scale_x
        self._scale_z = scale_z
        self._timer = Timer()
        self._rate = rospy.Rate(rate)
        self._enable_auto_control = False
        self.current_control = None 
        self.trajectory_index = None

        # callback data store
        self.image = None
        self.left_img = None 
        self.right_img = None 
        self.depth_img = None 
        self.me1_left = None
        self.me1_right =None
        self.me1_depth = None 
        self.me2_left = None
        self.me2_right = None
        self.me2_depth = None 
        self.me3_left = None
        self.me3_right = None
        self.me3_depth = None  
        self.intention = None
        self.manual_intention = 1
        self.imu = None
        self.odom = None
        self.speed = None
        self.labeled_control = None
        self.key = None
        self.training = False

        # subscribe ros messages
        rospy.Subscriber('/mynteye/left/image_raw/compressed', CompressedImage, self.cb_left_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye/right/image_raw/compressed', CompressedImage, self.cb_right_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye/depth/image_raw/compressed', CompressedImage, self.cb_depth_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_1/left/image_raw', Image, self.cb_me1_left_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_1/right/image_raw', Image, self.cb_me1_right_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_1/depth/image_raw', Image, self.cb_me1_depth_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_2/left/image_raw', Image, self.cb_me2_left_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_2/right/image_raw', Image, self.cb_me2_right_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_2/depth/image_raw', Image, self.cb_me2_depth_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_3/left/image_raw', Image, self.cb_me3_left_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_3/right/image_raw', Image, self.cb_me3_right_img, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/mynteye_3/depth/image_raw', Image, self.cb_me3_depth_img, queue_size=1, buff_size=2**10)
        if mode == 'DLM':
            # rospy.Subscriber('/intention_dlm', Int32, self.cb_dlm_intention, queue_size=1)
            rospy.Subscriber('/intention_int', Int32, self.cb_dlm_intention, queue_size=1)
        else:
            rospy.Subscriber('/intention_lpe', Image, self.cb_lpe_intention, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/speed', Float32, self.cb_speed, queue_size=1) 
        rospy.Subscriber('/odometry/filtered',Odometry,self.cb_odom,queue_size=1,buff_size=2**10)
        rospy.Subscriber('/mynteye/imu/data_raw',Imu,self.cb_imu,queue_size=1,buff_size=2**10)
        rospy.Subscriber('/labeled_control', Twist, self.cb_labeled_control, queue_size=1)
        rospy.Subscriber('/joy', Joy, self.cb_joy)
        
        # publish control
        self.control_pub = rospy.Publisher('/RosAria/cmd_vel', Twist, queue_size=1)

        # publishing as training data
        self.pub_trajectory_index = rospy.Publisher('/train/trajectory_index',String,queue_size=1)
        self.pub_teleop_vel = rospy.Publisher('/train/cmd_vel', Twist, queue_size=1)
        self.pub_left_img = rospy.Publisher('/train/mynteye/left_img', CompressedImage, queue_size=1)
        self.pub_right_img = rospy.Publisher('/train/mynteye/right_img',CompressedImage, queue_size=1)
        self.pub_depth_img = rospy.Publisher('/train/mynteye/depth_img', CompressedImage, queue_size=1)
        self.pub_me1_left_img = rospy.Publisher('/train/mynteye_1/left_img', Image, queue_size=1)
        self.pub_me1_right_img = rospy.Publisher('/train/mynteye_1/right_img',Image, queue_size=1)
        self.pub_me1_depth_img = rospy.Publisher('/train/mynteye_1/depth_img',Image, queue_size=1)
        self.pub_me2_left_img = rospy.Publisher('/train/mynteye_2/left_img', Image, queue_size=1)
        self.pub_me2_right_img = rospy.Publisher('/train/mynteye_2/right_img',Image, queue_size=1)
        self.pub_me2_depth_img = rospy.Publisher('/train/mynteye_2/depth_img',Image, queue_size=1)
        self.pub_me3_left_img = rospy.Publisher('/train/mynteye_3/left_img', Image, queue_size=1)
        self.pub_me3_right_img = rospy.Publisher('/train/mynteye_3/right_img',Image, queue_size=1)
        self.pub_me3_depth_img = rospy.Publisher('/train/mynteye_3/depth_img',Image, queue_size=1)
        self.pub_intention = rospy.Publisher('/train/intention', Int32, queue_size=1)
        self.pub_imu = rospy.Publisher('/train/imu', Imu, queue_size=1)
        self.pub_odom = rospy.Publisher('/train/odometry/filtered', Odometry, queue_size=1)
        self.pub_manual_intention  = rospy.Publisher('/train/manual_intention',Int32,queue_size=1)

    def cb_left_img(self, msg):
        self.left_img = msg
        #self.image = CvBridge().imgmsg_to_cv2(msg, desired_encoding='bgr8')

    def cb_right_img(self,msg):
        self.right_img = msg

    def cb_depth_img(self,msg):
        self.depth_img = msg

    def cb_me1_left_img(self,msg):
        self.me1_left = msg
    
    def cb_me1_right_img(self,msg):
        self.me1_right = msg
    
    def cb_me1_depth_img(self,msg):
        self.me1_depth = msg
    
    def cb_me2_left_img(self,msg):
        self.me2_left = msg
    
    def cb_me2_right_img(self,msg):
        self.me2_right = msg
    
    def cb_me2_depth_img(self,msg):
        self.me2_depth = msg

    def cb_me3_left_img(self,msg):
        self.me3_left = msg
    
    def cb_me3_right_img(self,msg):
        self.me3_right = msg

    def cb_me3_depth_img(self,msg):
        self.me3_depth = msg
    
    def cb_dlm_intention(self, msg):
        self.intention = msg.data

    def cb_lpe_intention(self, msg):
        self.intention = cv2.resize(CvBridge().imgmsg_to_cv2(msg, desired_encoding='bgr8'), (224, 224))

    def cb_speed(self, msg):
        self.speed = msg.data

    def cb_labeled_control(self, msg):
        self.labeled_control = msg

    def cb_imu(self,msg):
        self.imu = msg

    def cb_odom(self,msg):
        self.odom = msg

    def cb_joy(self, data):
        self.tele_twist.linear.x = self._scale_x * data.axes[JOY_MAPPING['axes']['left_stick_ud']]
        self.tele_twist.angular.z = self._scale_z * data.axes[JOY_MAPPING['axes']['left_stick_lr']]

        # parse control key
        if data.buttons[JOY_MAPPING['buttons']['A']] == 1:
            self._enable_auto_control = True
            print('Auto control')
        if data.buttons[JOY_MAPPING['buttons']['B']] == 1:
            self._enable_auto_control = False
            print('Manual control')
        if data.buttons[JOY_MAPPING['buttons']['back']] == 1:
            self.key = 'q'
        # toggle recording mode and generate trajectory index if start recording
        if data.buttons[JOY_MAPPING['buttons']['start']] == 1:
            self.key = 't'
            print('toggle training mode to: %s'%(not self.training))
            if not self.training:
                self.trajectory_index = self._random_string(15)

        # manual control the intention
        #STRAIGHT_FORWARD
        if data.buttons[JOY_MAPPING['buttons']['X']] == 1: 
            self.manual_intention =  0
            print('Intention is manually set to: %s'%(self.INTENTION_MAPPING[0]))
        #STOP
        if data.buttons[JOY_MAPPING['buttons']['Y']] == 1: 
            self.manual_intention = 1
            print('Intention is manually set to: %s'%(self.INTENTION_MAPPING[1]))
        #LEFT_TURN
        if data.buttons[JOY_MAPPING['buttons']['lt']] == 1 and self.manual_intention != self.INTENTION_MAPPING[2]:
            self.manual_intention = 2
            print('Intention is manually set to: %s'%(self.INTENTION_MAPPING[2]))
        #RIGHT_TURN
        if data.buttons[JOY_MAPPING['buttons']['rt']] == 1 and self.manual_intention != self.INTENTION_MAPPING[3]:
            self.manual_intention = 3
            print('Intention is manually set to: %s'%(self.INTENTION_MAPPING[3]))
    
    def _random_string(self,n):
        chars = string.ascii_letters+string.digits
        ret = ''.join(random.choice(chars) for _ in range(n))
        return ret

    def _on_loop(self, policy):
        """
        Logical loop
        """
        self._timer.tick()
        if self.key == 'q':
            sys.exit(-1)
        if self.key == 't':
            self.training = not self.training
            self.key = ''
        if self._enable_auto_control:
            if self.image is not None and self.intention is not None:
                #start = time.time()
                pred_control = policy.predict_control(self.image, self.intention, self.speed)[0]
                #end = time.time()
                #print ('=> predict time ', end - start)
                self.tele_twist.linear.x = pred_control[0]*Dataset.SCALE_VEL
                self.tele_twist.angular.z = pred_control[1]*Dataset.SCALE_STEER
                print('x: '+str(self.tele_twist.linear.x))
                print('z: '+str(self.tele_twist.angular.z))
        
        # publish to /train/* topic to record data (if in training mode)
        if self.training:
            self._publish_as_trn()

        # publish control
        self.control_pub.publish(self.tele_twist)
    
    def _publish_as_trn(self):
        if self.odom:
            self.pub_trajectory_index.publish(self.trajectory_index)
            self.pub_left_img.publish(self.left_img)
            self.pub_right_img.publish(self.right_img)
            self.pub_depth_img.publish(self.depth_img)
            self.pub_me1_left_img.publish(self.me1_left)
            self.pub_me1_right_img.publish(self.me1_right)
            self.pub_me1_depth_img.publish(self.me1_depth)
            self.pub_me2_left_img.publish(self.me2_left)
            self.pub_me2_right_img.publish(self.me2_right)
            self.pub_me2_depth_img.publish(self.me2_depth)
            self.pub_me3_left_img.publish(self.me3_left)
            self.pub_me3_right_img.publish(self.me3_right)
            self.pub_me3_depth_img.publish(self.me3_depth)
            self.pub_teleop_vel.publish(self.tele_twist)
            self.pub_intention.publish(self.intention)
            self.pub_imu.publish(self.imu)
            self.pub_odom.publish(self.odom)
            self.pub_manual_intention.publish(self.manual_intention)

    def text_to_screen(self, text, color = (200, 000, 000), pos=(WINDOW_WIDTH/2, 30), size=30):
        text = str(text)
        font = pygame.font.SysFont('Comic Sans MS', size*SCREEN_SCALE)#pygame.font.Font(font_type, size)
        text = font.render(text, True, color)
        text_rect = text.get_rect(center=(pos[0]*SCREEN_SCALE, pos[1]*SCREEN_SCALE))
        self._display.blit(text, text_rect)

    def get_vertical_rect(self, value, pos):
        pos = (pos[0]*SCREEN_SCALE, pos[1]*SCREEN_SCALE)
        scale = 20*SCREEN_SCALE
        if value > 0:
            return pygame.Rect((pos[0], pos[1]-value*scale), (scale, value*scale))
        else:
            return pygame.Rect(pos, (scale, -value*scale))

    def get_horizontal_rect(self, value, pos):
        pos = (pos[0]*SCREEN_SCALE, pos[1]*SCREEN_SCALE)
        scale = 20*SCREEN_SCALE
        if value > 0:
            return pygame.Rect((pos[0]-value*scale, pos[1]), (value*scale, scale))
        else:
            return pygame.Rect(pos, (-value*scale, scale))

    def control_bar(self, pos=(WINDOW_WIDTH-100, WINDOW_HEIGHT-150)):
        acc_rect = self.get_vertical_rect(self.tele_twist.linear.x, pos)
        pygame.draw.rect(self._display, (0, 255, 0), acc_rect)
        steer_rect = self.get_horizontal_rect(self.tele_twist.angular.z, (pos[0], pos[1]+110))
        pygame.draw.rect(self._display, (0, 255, 0), steer_rect)
        if self.labeled_control is not None:
            pygame.draw.rect(self._display, (255, 0, 0), self.get_vertical_rect(self.labeled_control.linear.x, (pos[0]-20, pos[1])))
            pygame.draw.rect(self._display, (255, 0, 0), self.get_horizontal_rect(self.labeled_control.angular.z, (pos[0], pos[1]+130)))

    def _on_render(self):
        """
        render loop
        """
        if self.image is not None:
            array = cv2.resize(self.image, (WINDOW_WIDTH*SCREEN_SCALE, WINDOW_HEIGHT*SCREEN_SCALE))
            surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
            self._display.blit(surface, (0, 0))
        if self.speed is not None:
            self.text_to_screen('Speed: {:.4f} m/s'.format(self.speed), pos=(150, WINDOW_HEIGHT-30))
        if self.intention is not None:
            if self._mode == 'DLM':
                self.text_to_screen(INTENTION[self.intention])
            else:
                surface = pygame.surfarray.make_surface(self.intention.swapaxes(0, 1))
                self._display.blit(surface, (SCREEN_SCALE*(WINDOW_WIDTH-self.intention.shape[0])/2, 0))

        self.control_bar()
        self.text_to_screen("Auto: {}".format(self._enable_auto_control), pos=(150, WINDOW_HEIGHT-70))

        pygame.display.flip()

    def _initialize_game(self):
        self._display = pygame.display.set_mode(
                (WINDOW_WIDTH*SCREEN_SCALE, WINDOW_HEIGHT*SCREEN_SCALE),
                pygame.HWSURFACE | pygame.DOUBLEBUF)

    def execute(self, policy):
        pygame.init()
        self._initialize_game()
        try:
            while True:
                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        sys.exit(-1)

                self._on_loop(policy)
                self._on_render()
                self._rate.sleep()
        finally:
            pygame.quit()

# wrapper for fire to get command arguments
def run_wrapper(mode='DLM', input_frame='NORMAL', model_dir=None, num_intentions=4, scale_x=1, scale_z=1, rate=24):
    rospy.init_node("joy_controller")
    controller = Controller(mode, scale_x, scale_z, rate)
    if model_dir == None:
        policy = None
    else:    
        policy = Policy(mode, input_frame, 2, model_dir, num_intentions)
    controller.execute(policy)

def main():
    fire.Fire(run_wrapper)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print ('\nCancelled by user! Bye Bye!')