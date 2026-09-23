# Hardware platform

Physical validation used two modified AgileX LIMO differential-drive robots: LIMO-01 and LIMO-02. Each robot carried an Intel NUC i7 running Ubuntu 22.04 and ROS 2 Humble, an EAI T-mini Pro 2D LiDAR, and an Orbbec DaBai RGB-D camera. A Vicon system supplied ground-truth pose streams.

Inter-robot communication used REYAX RYLR998 modules at 868 MHz, SF7, 125 kHz bandwidth, and coding rate 4/5. The scheduler configures a 1% duty-cycle ceiling over a 60-second rolling window. The physical study is \(N=2\) only.
