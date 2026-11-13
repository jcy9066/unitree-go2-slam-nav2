#include <cmath>
#include <memory>
#include "gtest/gtest.h"
#include "rcl/time.h"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_lifecycle/lifecycle_node.hpp"
#include "nav2_controller/plugins/simple_progress_checker.hpp"
#include "nav2_controller/plugins/pose_progress_checker.hpp"

class TurnProgress : public ::testing::Test
{
protected:
  static void SetUpTestSuite() {rclcpp::init(0, nullptr);}
  static void TearDownTestSuite() {rclcpp::shutdown();}
  void SetUp() override
  {
    node = std::make_shared<rclcpp_lifecycle::LifecycleNode>("turn_progress_test");
    node->declare_parameter("pose.required_movement_angle", 0.10);
    simple.initialize(node, "simple");
    pose.initialize(node, "pose");
    ASSERT_EQ(rcl_enable_ros_time_override(node->get_clock()->get_clock_handle()), RCL_RET_OK);
  }
  geometry_msgs::msg::PoseStamped at(double seconds, double x, double yaw)
  {
    EXPECT_EQ(rcl_set_ros_time_override(node->get_clock()->get_clock_handle(),
      static_cast<int64_t>(seconds * 1e9)), RCL_RET_OK);
    geometry_msgs::msg::PoseStamped p;
    p.pose.position.x = x;
    p.pose.orientation.z = std::sin(yaw / 2.);
    p.pose.orientation.w = std::cos(yaw / 2.);
    return p;
  }
  std::shared_ptr<rclcpp_lifecycle::LifecycleNode> node;
  nav2_controller::SimpleProgressChecker simple;
  nav2_controller::PoseProgressChecker pose;
};

TEST_F(TurnProgress, ActualTurnCountsWithoutTranslation)
{
  // Return-turn observations, rounded from the 2026-11-12 trace. The pause
  // between turns must not erase already observed angular progress.
  const double yaw[] = {-2.149,-2.277,-2.372,-2.438,-2.499,-2.398,-2.382,-2.369,
    -2.365,-2.364,-2.443,-2.514,-2.547,-2.550,-2.551,-2.551,-2.552,-2.551,
    -2.454,-2.417,-2.408,-2.471,-2.538,-2.598,-2.669,-2.753,-2.840,-2.908,-2.982};
  int old_failures = 0;
  for (size_t i = 0; i < sizeof(yaw)/sizeof(*yaw); ++i) {
    auto p = at(1. + .94 * i, 0., yaw[i]);
    old_failures += !simple.check(p);
    EXPECT_TRUE(pose.check(p));
  }
  EXPECT_GT(old_failures, 0);
}

TEST_F(TurnProgress, StationaryAndTinyHeadingNoiseStillFail)
{
  auto p = at(1., 0., 0.);
  ASSERT_TRUE(simple.check(p)); ASSERT_TRUE(pose.check(p));
  p = at(12., .001, .005);  // below either physical-progress threshold
  EXPECT_FALSE(simple.check(p)); EXPECT_FALSE(pose.check(p));
}

TEST_F(TurnProgress, TranslationAndResetRemainAvailable)
{
  for (int i = 1; i < 30; ++i) {
    auto p = at(i, .2 * i, 0.);
    EXPECT_TRUE(simple.check(p)); EXPECT_TRUE(pose.check(p));
  }
  simple.reset(); pose.reset();
  auto p = at(100., 0., 0.);
  EXPECT_TRUE(simple.check(p)); EXPECT_TRUE(pose.check(p));
}
