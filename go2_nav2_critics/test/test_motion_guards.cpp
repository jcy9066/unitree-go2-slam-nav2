#include <cmath>
#include <limits>
#include <memory>
#include "gtest/gtest.h"
#include "dwb_core/trajectory_critic.hpp"
#include "dwb_core/exceptions.hpp"
#include "dwb_critics/base_obstacle.hpp"
#include "dwb_critics/obstacle_footprint.hpp"
#include "nav2_costmap_2d/costmap_2d.hpp"
#include "pluginlib/class_loader.hpp"

TEST(WalkingSpeed, RejectsTinyTranslationEvenWhenTurning)
{
  pluginlib::ClassLoader<dwb_core::TrajectoryCritic> loader("dwb_core", "dwb_core::TrajectoryCritic");
  auto critic = loader.createSharedInstance("go2_nav2_critics::WalkingSpeedCritic");
  dwb_msgs::msg::Trajectory2D t;
  t.velocity.x = 0.08; t.velocity.theta = 0.8;
  EXPECT_THROW(critic->scoreTrajectory(t), dwb_core::IllegalTrajectoryException);
  t.velocity.x = 0.2;
  EXPECT_DOUBLE_EQ(critic->scoreTrajectory(t), 0.0);
  t.velocity.x = 0.3;
  EXPECT_DOUBLE_EQ(critic->scoreTrajectory(t), 0.0);
  t.velocity.x = 0.0;
  EXPECT_DOUBLE_EQ(critic->scoreTrajectory(t), 0.0);  // in-place turn is retained
  t.velocity.theta = 0.0;
  EXPECT_DOUBLE_EQ(critic->scoreTrajectory(t), 0.0);  // stop is retained
  t.velocity.x = std::numeric_limits<double>::quiet_NaN();
  EXPECT_THROW(critic->scoreTrajectory(t), dwb_core::IllegalTrajectoryException);
}

class CenterCritic : public dwb_critics::BaseObstacleCritic
{
public:
  explicit CenterCritic(nav2_costmap_2d::Costmap2D * map) {costmap_ = map; sum_scores_ = false;}
};
class BodyCritic : public dwb_critics::ObstacleFootprintCritic
{
public:
  explicit BodyCritic(nav2_costmap_2d::Costmap2D * map)
  {
    costmap_ = map; sum_scores_ = false;
    for (auto xy : {std::pair<double,double>{-.42,-.23},{.42,-.23},{.42,.23},{-.42,.23}}) {
      geometry_msgs::msg::Point p; p.x=xy.first; p.y=xy.second; footprint_spec_.push_back(p);
    }
  }
};
TEST(BodyCollision, RejectsFrontOverlapThatCenterCheckMisses)
{
  nav2_costmap_2d::Costmap2D map(200,200,.01,-1.,-1.,0);
  unsigned int wall_x, wall_y; ASSERT_TRUE(map.worldToMap(.30,0.,wall_x,wall_y));
  for (unsigned int y=0; y<200; ++y) map.setCost(wall_x,y,254);
  CenterCritic center(&map); BodyCritic body(&map); geometry_msgs::msg::Pose2D p;
  EXPECT_DOUBLE_EQ(center.scorePose(p),0.0);
  EXPECT_THROW(body.scorePose(p),dwb_core::IllegalTrajectoryException);
  p.theta = std::acos(-1.)/2.;
  EXPECT_DOUBLE_EQ(body.scorePose(p),0.0);  // narrow side fits after rotation
}
