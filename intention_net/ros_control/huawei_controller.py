"""
Run the learned model to connect to client with ros messages
"""
import pygame
import time
import sys
import fire

# import local file
from joy_teleop import JOY_MAPPING
from policy import Policy
# ros packages
import rospy
from sensor_msgs.msg import Joy, Image, Imu
from geometry_msgs.msg import Twist
from std_msgs.msg import Int32, Float32
import cv2
from cv_bridge import CvBridge
from intention_net.dataset import HuaWeiFinalDataset as Dataset

# SCREEN SCALE IS FOR high dpi screen, i.e. 4K screen
SCREEN_SCALE = 2
WINDOW_WIDTH = 1024
WINDOW_HEIGHT = 768
VIS_INTENTION = {
    0: 'STRAIGHT_FORWARD',
    1: 'LEFT_TURN',
    2: 'RIGHT_TURN',
}

def msg_to_img(msg, decoding='rgb8'):
    return cv2.resize(CvBridge().imgmsg_to_cv2(msg, desired_encoding=decoding), (224, 224))

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
        self._mode = mode
        self._scale_x = scale_x
        self._scale_z = scale_z
        self._timer = Timer()
        self._rate = rospy.Rate(rate)
        self._enable_auto_control = False
        # callback data store
        self.image = None
        self.front_image, self.fl_image, self.fr_image = None, None, None
        self.intention = None
        self.speed = None
        self.labeled_control = None
        self.key = None
        self.input_frame = None
        # subscribe ros messages
        rospy.Subscriber('/image', Image, self.cb_image, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/front_96_image', Image, self.cb_front_image, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/fl_96_image', Image, self.cb_fl_image, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/fr_96_image', Image, self.cb_fr_image, queue_size=1, buff_size=2**10)

        if mode == 'DLM':
            rospy.Subscriber('/intention_dlm', Imu, self.cb_dlm_intention, queue_size=1)
        else:
            rospy.Subscriber('/intention_lpe', Image, self.cb_lpe_intention, queue_size=1, buff_size=2**10)
        rospy.Subscriber('/speed', Imu, self.cb_speed, queue_size=1)
        rospy.Subscriber('/control', Imu, self.cb_labeled_control, queue_size=1)
        rospy.Subscriber('/joy', Joy, self.cb_joy)
        # publish control
        self.control_pub = rospy.Publisher('/t_control', Twist, queue_size=1)

    def cb_image(self, msg):
        self.image = msg_to_img(msg)

    def cb_front_image(self, msg):
        self.front_image = msg_to_img(msg)

    def cb_fl_image(self, msg):
        self.fl_image = msg_to_img(msg)

    def cb_fr_image(self, msg):
        self.fr_image = msg_to_img(msg)

    def cb_lpe_intention(self, msg):
        self.intention = msg_to_img(msg)

    def cb_dlm_intention(self, msg):
        self.intention = Dataset.INTENTION[int(msg.linear_acceleration.x)]

    def cb_speed(self, msg):
        self.speed = msg.linear_acceleration.x

    def cb_labeled_control(self, msg):
        t = Twist()
        t.linear.x = msg.linear_acceleration.x
        t.angular.z = msg.angular_velocity.z
        self.labeled_control = t

    def cb_joy(self, data):
        self.tele_twist.linear.x = self._scale_x * data.axes[JOY_MAPPING['axes']['left_stick_ud']]
        self.tele_twist.angular.z = -self._scale_z * data.axes[JOY_MAPPING['axes']['left_stick_lr']]

        # parse control key
        if data.buttons[JOY_MAPPING['buttons']['A']] == 1:
            self._enable_auto_control = True
        if data.buttons[JOY_MAPPING['buttons']['B']] == 1:
            self._enable_auto_control = False
        if data.buttons[JOY_MAPPING['buttons']['back']] == 1:
            self.key = 'q'

    def _on_loop(self, policy):
        """
        Logical loop
        """
        self._timer.tick()
        if self.key == 'q':
            sys.exit(-1)
        if self._enable_auto_control:
            self.input_frame = policy.input_frame
            if policy.input_frame != 'MULTI':
                if self.image is not None and self.intention is not None and self.speed is not None:
                    #start = time.time()
                    pred_control = policy.predict_control(self.image, self.intention, self.speed)[0]
                    #end = time.time()
                    #print ('=> predict time ', end - start)
                    self.tele_twist.linear.x = pred_control[1]*Dataset.SCALE_ACC
                    self.tele_twist.angular.z = pred_control[0]*Dataset.SCALE_STEER
            else:
                if self.image is not None and self.fl_image is not None and self.fr_image is not None and self.intention is not None and self.speed is not None:
                    # here use 60 front image
                    pred_control = policy.predict_control([self.fl_image, self.image, self.fr_image], self.intention, self.speed)[0]
                    self.tele_twist.linear.x = pred_control[1]*Dataset.SCALE_ACC
                    self.tele_twist.angular.z = pred_control[0]*Dataset.SCALE_STEER
        # publish control
        self.control_pub.publish(self.tele_twist)

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
        if self.input_frame != 'MULTI':
            if self.image is not None:
                array = cv2.resize(self.image, (WINDOW_WIDTH*SCREEN_SCALE, WINDOW_HEIGHT*SCREEN_SCALE))
                surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
                self._display.blit(surface, (0, 0))
        else:
            width = int(WINDOW_WIDTH/3)*SCREEN_SCALE
            if self.image is not None:
                array = cv2.resize(self.image, (WINDOW_WIDTH*SCREEN_SCALE, WINDOW_HEIGHT*SCREEN_SCALE-width))
                surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
                self._display.blit(surface, (0, width))
            if self.front_image is not None:
                array = cv2.resize(self.front_image, (width, width))
                surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
                self._display.blit(surface, (width, 0))
            if self.fl_image is not None:
                array = cv2.resize(self.fl_image, (width, width))
                surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
                self._display.blit(surface, (0, 0))
            if self.fr_image is not None:
                array = cv2.resize(self.fr_image, (width, width))
                surface = pygame.surfarray.make_surface(array.swapaxes(0, 1))
                self._display.blit(surface, (width*2, 0))

        if self.speed is not None:
            self.text_to_screen('Speed: {:.4f} m/s'.format(self.speed), pos=(150, WINDOW_HEIGHT-30))
        if self.intention is not None:
            if self._mode == 'DLM':
                self.text_to_screen(VIS_INTENTION[self.intention])
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
def run_wrapper(model_dir, mode, input_frame, num_intentions=3, scale_x=1, scale_z=1, rate=28):
    rospy.init_node("joy_controller")
    controller = Controller(mode, scale_x, scale_z, rate)
    policy = Policy(mode, input_frame, 2, model_dir, num_intentions)
    controller.execute(policy)

def main():
    fire.Fire(run_wrapper)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print ('\nCancelled by user! Bye Bye!')
