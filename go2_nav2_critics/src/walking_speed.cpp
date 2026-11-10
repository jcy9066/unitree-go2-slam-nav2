// DWB rejects sub-walking translation instead of boosting an already chosen command.
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <limits>
#include <vector>
#include "dwb_core/exceptions.hpp"
#include "dwb_core/trajectory_critic.hpp"
#include "nav2_util/node_utils.hpp"
#include "pluginlib/class_list_macros.hpp"

namespace go2_nav2_critics
{
class WalkingSpeedCritic : public dwb_core::TrajectoryCritic
{
public:
  void onInit() override
  {
    auto node = node_.lock();
    if (!node) {
      throw std::runtime_error("WalkingSpeedCritic has no lifecycle node");
    }
    const auto parameter = dwb_plugin_name_ + "." + name_ + ".minimum_translation_speed";
    nav2_util::declare_parameter_if_not_declared(node, parameter, rclcpp::ParameterValue(0.2));
    minimum_ = node->get_parameter(parameter).as_double();
    if (!std::isfinite(minimum_) || minimum_ <= 0.0) {
      throw std::invalid_argument("minimum_translation_speed must be finite and positive");
    }
  }

  double scoreTrajectory(const dwb_msgs::msg::Trajectory2D & trajectory) override
  {
    const auto & velocity = trajectory.velocity;
    const double speed = std::hypot(velocity.x, velocity.y);
    if (!std::isfinite(speed) || !std::isfinite(velocity.theta)) {
      throw dwb_core::IllegalTrajectoryException(name_, "Nonfinite walking velocity");
    }
    // Native DWB's minimum-speed condition is translation OR rotation. A turn
    // can therefore admit tiny translation, which stalled this Go2 in testing.
    // Zero translation still allows in-place rotation and a stopped command.
    if (speed > 1e-6 && speed + 1e-6 < minimum_) {
      throw dwb_core::IllegalTrajectoryException(name_, "Translation below walking threshold");
    }
    return 0.0;
  }

private:
  double minimum_{0.2};
};


}  // namespace go2_nav2_critics
PLUGINLIB_EXPORT_CLASS(go2_nav2_critics::WalkingSpeedCritic, dwb_core::TrajectoryCritic)
