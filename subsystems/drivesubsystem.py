from commands2 import SubsystemBase
from wpilib import Encoder, PWMVictorSPX, RobotBase, Timer
from ctre import (
    AbsoluteSensorRange,
    CANCoder,
    ControlMode,
    ErrorCode,
    SensorInitializationStrategy,
    WPI_TalonFX,
)
from navx import AHRS
from wpimath.geometry import Rotation2d
from wpimath.geometry._geometry import Pose2d
from wpimath.kinematics import (
    ChassisSpeeds,
    SwerveModuleState,
    SwerveDrive4Kinematics,
    SwerveDrive4Odometry,
)

import constants


class SwerveModule:
    def __init__(self, name: str) -> None:
        self.name = name

    def getSwerveAngle(self) -> Rotation2d:
        raise NotImplementedError("Must be implemented by subclass")

    def setSwerveAngle(self, swerveAngle: Rotation2d) -> None:
        raise NotImplementedError("Must be implemented by subclass")

    def setSwerveAngleTarget(self, swerveAngleTarget: Rotation2d) -> None:
        raise NotImplementedError("Must be implemented by subclass")

    def getWheelLinearVelocity(self) -> float:
        raise NotImplementedError("Must be implemented by subclass")

    def setWheelLinearVelocityTarget(self, wheelLinearVelocityTarget: float) -> None:
        raise NotImplementedError("Must be implemented by subclass")

    def getState(self) -> SwerveModuleState:
        return SwerveModuleState(
            self.getWheelLinearVelocity(),
            self.getSwerveAngle(),
        )

    def applyState(self, state: SwerveModuleState) -> None:
        # optimizedState = SwerveModuleState.optimize(state, self.getSwerveAngle())
        optimizedState = state
        self.setWheelLinearVelocityTarget(optimizedState.speed)
        self.setSwerveAngleTarget(optimizedState.angle)


class PWMSwerveModule(SwerveModule):
    """
    Implementation of SwerveModule designed for ease of simulation:
        wheelMotor: 1:1 gearing with wheel
        swerveMotor: 1:1 gearing with swerve
        wheelEncoder: wheel distance (meters)
        swerveEncoder: swerve angle (radians)
    """

    def __init__(
        self,
        name: str,
        wheelMotor: PWMVictorSPX,
        swerveMotor: PWMVictorSPX,
        wheelEncoder: Encoder,
        swerveEncoder: Encoder,
    ) -> None:
        SwerveModule.__init__(self, name)
        self.wheelMotor = wheelMotor
        self.swerveMotor = swerveMotor
        self.wheelEncoder = wheelEncoder
        self.swerveEncoder = swerveEncoder

        self.wheelEncoder.setDistancePerPulse(1 / constants.kWheelEncoderPulsesPerMeter)
        self.swerveEncoder.setDistancePerPulse(
            1 / constants.kSwerveEncoderPulsesPerRadian
        )

    def getSwerveAngle(self) -> Rotation2d:
        return Rotation2d(self.swerveEncoder.getDistance())

    def setSwerveAngleTarget(self, swerveAngleTarget: Rotation2d) -> None:
        swerveError = swerveAngleTarget.radians() - self.swerveEncoder.getDistance()
        swerveErrorClamped = min(max(swerveError, -1), 1)
        self.swerveMotor.setSpeed(swerveErrorClamped)

    def getWheelLinearVelocity(self) -> float:
        return self.wheelEncoder.getRate()

    def setWheelLinearVelocityTarget(self, wheelLinearVelocityTarget: float) -> None:
        speedFactor = wheelLinearVelocityTarget / constants.kMaxWheelLinearVelocity
        speedFactorClamped = min(max(speedFactor, -1), 1)
        self.wheelMotor.setSpeed(speedFactorClamped)


class CTRESwerveModule(SwerveModule):
    """
    Implementation of SwerveModule for the SDS swerve modules
    https://www.swervedrivespecialties.com/collections/kits/products/mk4-swerve-module
        driveMotor: Falcon 500 Motor (with built-in encoder) attached to wheel through gearing
        steerMotor: Falcon 500 Motor (with built-in encoder) attached to swerve through gearing
        swerveEncoder: CANCoder
    """

    def __init__(
        self,
        name: str,
        driveMotor: WPI_TalonFX,
        steerMotor: WPI_TalonFX,
        swerveEncoder: CANCoder,
        swerveEncoderOffset: float,
    ) -> None:
        SwerveModule.__init__(self, name)
        self.driveMotor = driveMotor
        self.steerMotor = steerMotor
        self.swerveEncoder = swerveEncoder
        self.swerveEncoderOffset = swerveEncoderOffset

        def ctreCheckError(name: str, errorCode: ErrorCode) -> bool:
            if (errorCode is not None) and (errorCode != ErrorCode.OK):
                print("ERROR: {}: {}".format(name, errorCode))
                return False
            return True

        print("Initializing swerve module: {}".format(self.name))
        print(
            "   Configuring swerve encoder: CAN ID: {}".format(
                self.swerveEncoder.getDeviceNumber()
            )
        )
        if not ctreCheckError(
            "configFactoryDefault",
            self.swerveEncoder.configFactoryDefault(
                constants.kConfigurationTimeoutLimit
            ),
        ):
            return
        if not ctreCheckError(
            "configSensorInitializationStrategy",
            self.swerveEncoder.configSensorInitializationStrategy(
                SensorInitializationStrategy.BootToAbsolutePosition,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "configMagnetOffset",
            self.swerveEncoder.configMagnetOffset(
                -1 * self.swerveEncoderOffset,  # invert the offset to zero the encoder
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "configAbsoluteSensorRange",
            self.swerveEncoder.configAbsoluteSensorRange(
                AbsoluteSensorRange.Signed_PlusMinus180,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "setPositionToAbsolute",
            self.swerveEncoder.setPositionToAbsolute(
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        print("   ... Done")
        print(
            "   Configuring drive motor: CAN ID: {}".format(
                self.driveMotor.getDeviceID()
            )
        )
        if not ctreCheckError(
            "configFactoryDefault",
            self.driveMotor.configFactoryDefault(constants.kConfigurationTimeoutLimit),
        ):
            return
        # config = TalonFXConfiguration()
        # if not ctreCheckError(
        #     "getAllConfigs",
        #     self.driveMotor.getAllConfigs(config, constants.kConfigurationTimeoutLimit),
        # ):
        #     return
        # else:
        #     print("   Config:\n{}".format(config.toString()))
        if not ctreCheckError(
            "config_kP",
            self.driveMotor.config_kP(
                constants.kDrivePIDSlot,
                constants.kDrivePGain,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "config_kI",
            self.driveMotor.config_kI(
                constants.kDrivePIDSlot,
                constants.kDriveIGain,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "config_kD",
            self.driveMotor.config_kD(
                constants.kDrivePIDSlot,
                constants.kDriveDGain,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        print("   ... Done")

        print(
            "   Configuring steer motor: CAN ID: {}".format(
                self.steerMotor.getDeviceID()
            )
        )
        if not ctreCheckError(
            "configFactoryDefault",
            self.steerMotor.configFactoryDefault(constants.kConfigurationTimeoutLimit),
        ):
            return
        # config = TalonFXConfiguration()
        # if not ctreCheckError(
        #     "getAllConfigs",
        #     self.driveMotor.getAllConfigs(config, constants.kConfigurationTimeoutLimit),
        # ):
        #     return
        # else:
        #     print("   Config:\n{}".format(config.toString()))
        if not ctreCheckError(
            "config_kP",
            self.steerMotor.config_kP(
                constants.kSteerPIDSlot,
                constants.kSteerPGain,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "config_kI",
            self.steerMotor.config_kI(
                constants.kSteerPIDSlot,
                constants.kSteerIGain,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        if not ctreCheckError(
            "config_kD",
            self.steerMotor.config_kD(
                constants.kSteerPIDSlot,
                constants.kSteerDGain,
                constants.kConfigurationTimeoutLimit,
            ),
        ):
            return
        print("   ... Done")

        print("... Done")

    def getSwerveAngle(self) -> Rotation2d:
        steerEncoderPulses = self.steerMotor.getSelectedSensorPosition()
        swerveAngle = steerEncoderPulses / constants.kSwerveEncoderPulsesPerRadian
        # print("Steer[{}]: {}".format(self.steerMotor.getDeviceID(), swerveAngle))
        return Rotation2d(swerveAngle)

    def setSwerveAngle(self, swerveAngle: Rotation2d) -> None:
        steerEncoderPulses = (
            swerveAngle.radians() * constants.kSwerveEncoderPulsesPerRadian
        )
        self.steerMotor.setSelectedSensorPosition(steerEncoderPulses)

    def setSwerveAngleTarget(self, swerveAngleTarget: Rotation2d) -> None:
        steerEncoderPulsesTarget = (
            swerveAngleTarget.radians() * constants.kSwerveEncoderPulsesPerRadian
        )
        self.steerMotor.set(ControlMode.Position, steerEncoderPulsesTarget)

    def getWheelLinearVelocity(self) -> float:
        driveEncoderPulsesPerSecond = (
            self.driveMotor.getSelectedSensorVelocity()
            * constants.k100MillisecondsPerSecond
        )
        wheelLinearVelocity = (
            driveEncoderPulsesPerSecond / constants.kWheelEncoderPulsesPerMeter
        )
        return wheelLinearVelocity

    def setWheelLinearVelocityTarget(self, wheelLinearVelocityTarget: float) -> None:
        driveEncoderPulsesPerSecond = (
            wheelLinearVelocityTarget * constants.kWheelEncoderPulsesPerMeter
        )
        self.driveMotor.set(
            ControlMode.Velocity,
            driveEncoderPulsesPerSecond / constants.k100MillisecondsPerSecond,
        )


class DriveSubsystem(SubsystemBase):
    def __init__(self) -> None:
        SubsystemBase.__init__(self)
        self.setName(__class__.__name__)

        if RobotBase.isReal():
            self.frontLeftModule = CTRESwerveModule(
                constants.kFrontLeftModuleName,
                WPI_TalonFX(constants.kFrontLeftDriveMotorId),
                WPI_TalonFX(constants.kFrontLeftSteerMotorId),
                CANCoder(constants.kFrontLeftSteerEncoderId),
                constants.kFrontLeftAbsoluteEncoderOffset,
            )
            self.frontRightModule = CTRESwerveModule(
                constants.kFrontRightModuleName,
                WPI_TalonFX(constants.kFrontRightDriveMotorId),
                WPI_TalonFX(constants.kFrontRightSteerMotorId),
                CANCoder(constants.kFrontRightSteerEncoderId),
                constants.kFrontRightAbsoluteEncoderOffset,
            )
            self.backLeftModule = CTRESwerveModule(
                constants.kBackLeftModuleName,
                WPI_TalonFX(constants.kBackLeftDriveMotorId),
                WPI_TalonFX(constants.kBackLeftSteerMotorId),
                CANCoder(constants.kBackLeftSteerEncoderId),
                constants.kBackLeftAbsoluteEncoderOffset,
            )
            self.backRightModule = CTRESwerveModule(
                constants.kBackRightModuleName,
                WPI_TalonFX(constants.kBackRightDriveMotorId),
                WPI_TalonFX(constants.kBackRightSteerMotorId),
                CANCoder(constants.kBackRightSteerEncoderId),
                constants.kBackRightAbsoluteEncoderOffset,
            )
        else:
            self.frontLeftModule = PWMSwerveModule(
                constants.kFrontLeftModuleName,
                PWMVictorSPX(constants.kFrontLeftDriveMotorSimPort),
                PWMVictorSPX(constants.kFrontLeftSteerMotorSimPort),
                Encoder(*constants.kFrontLeftDriveEncoderSimPorts),
                Encoder(*constants.kFrontLeftSteerEncoderSimPorts),
            )
            self.frontRightModule = PWMSwerveModule(
                constants.kFrontRightModuleName,
                PWMVictorSPX(constants.kFrontRightDriveMotorSimPort),
                PWMVictorSPX(constants.kFrontRightSteerMotorSimPort),
                Encoder(*constants.kFrontRightDriveEncoderSimPorts),
                Encoder(*constants.kFrontRightSteerEncoderSimPorts),
            )
            self.backLeftModule = PWMSwerveModule(
                constants.kBackLeftModuleName,
                PWMVictorSPX(constants.kBackLeftDriveMotorSimPort),
                PWMVictorSPX(constants.kBackLeftSteerMotorSimPort),
                Encoder(*constants.kBackLeftDriveEncoderSimPorts),
                Encoder(*constants.kBackLeftSteerEncoderSimPorts),
            )
            self.backRightModule = PWMSwerveModule(
                constants.kBackRightModuleName,
                PWMVictorSPX(constants.kBackRightDriveMotorSimPort),
                PWMVictorSPX(constants.kBackRightSteerMotorSimPort),
                Encoder(*constants.kBackRightDriveEncoderSimPorts),
                Encoder(*constants.kBackRightSteerEncoderSimPorts),
            )

        self.modules = (
            self.frontLeftModule,
            self.frontRightModule,
            self.backLeftModule,
            self.backRightModule,
        )

        self.kinematics = SwerveDrive4Kinematics(
            constants.kFrontLeftWheelPosition,
            constants.kFrontRightWheelPosition,
            constants.kBackLeftWheelPosition,
            constants.kBackRightWheelPosition,
        )

        # Create the gyro, a sensor which can indicate the heading of the robot relative
        # to a customizable position.
        self.gyro = AHRS.create_spi()

        # Create the an object for our odometry, which will utilize sensor data to
        # keep a record of our position on the field.
        self.odometry = SwerveDrive4Odometry(self.kinematics, self.gyro.getRotation2d())

        self.printTimer = Timer()
        self.printTimer.start()

    def resetSwerveModules(self):
        for module in self.modules:
            swerveEncoderAngle = (
                module.swerveEncoder.getAbsolutePosition() * constants.kRadiansPerDegree
            )
            module.setSwerveAngle(Rotation2d(swerveEncoderAngle))
        self.odometry.resetPosition(Pose2d(), self.gyro.getRotation2d())

    def periodic(self):
        """
        Called periodically when it can be called. Updates the robot's
        odometry with sensor data.
        """
        self.odometry.update(
            self.gyro.getRotation2d(),
            self.frontLeftModule.getState(),
            self.frontRightModule.getState(),
            self.backLeftModule.getState(),
            self.backRightModule.getState(),
        )

        if self.printTimer.hasPeriodPassed(constants.kPrintPeriod):
            rX = self.odometry.getPose().translation().X()
            rY = self.odometry.getPose().translation().Y()
            rAngle = int(self.odometry.getPose().rotation().degrees())

            flAngle = int(self.frontLeftModule.getSwerveAngle().degrees())
            frAngle = int(self.frontRightModule.getSwerveAngle().degrees())
            blAngle = int(self.backLeftModule.getSwerveAngle().degrees())
            brAngle = int(self.backRightModule.getSwerveAngle().degrees())

            flSpeed = self.frontLeftModule.getWheelLinearVelocity()
            frSpeed = self.frontRightModule.getWheelLinearVelocity()
            blSpeed = self.backLeftModule.getWheelLinearVelocity()
            brSpeed = self.backRightModule.getWheelLinearVelocity()

            print(
                "r: {:.1f}, {:.1f}, {}* fl: {}* {:.1f} fr: {}* {:.1f} bl: {}* {:.1f} br: {}* {:.1f}".format(
                    rX,
                    rY,
                    rAngle,
                    flAngle,
                    flSpeed,
                    frAngle,
                    frSpeed,
                    blAngle,
                    blSpeed,
                    brAngle,
                    brSpeed,
                )
            )

    def arcadeDriveWithFactors(
        self,
        forwardSpeedFactor: float,
        sidewaysSpeedFactor: float,
        rotationSpeedFactor: float,
    ) -> None:
        """
        Drives the robot using arcade controls.

        :param forwardSpeedFactor: the commanded forward movement
        :param sidewaysSpeedFactor: the commanded sideways movement
        :param rotationSpeedFactor: the commanded rotation
        """
        # print(
        #     "inputs: x: {:.2f} y: {:.2f} *: {:.2f}".format(
        #         forwardSpeedFactor, sidewaysSpeedFactor, rotationSpeedFactor
        #     )
        # )
        chassisSpeeds = ChassisSpeeds(
            forwardSpeedFactor * constants.kMaxForwardLinearVelocity,
            sidewaysSpeedFactor * constants.kMaxSidewaysLinearVelocity,
            rotationSpeedFactor * constants.kMaxRotationAngularVelocity,
        )

        self.arcadeDriveWithSpeeds(chassisSpeeds)

    def arcadeDriveWithSpeeds(self, chassisSpeeds: ChassisSpeeds) -> None:
        moduleStates = self.kinematics.toSwerveModuleStates(chassisSpeeds)
        (
            frontLeftState,
            frontRightState,
            backLeftState,
            backRightState,
        ) = SwerveDrive4Kinematics.normalizeWheelSpeeds(
            moduleStates, constants.kMaxWheelLinearVelocity
        )
        self.frontLeftModule.applyState(frontLeftState)
        self.frontRightModule.applyState(frontRightState)
        self.backLeftModule.applyState(backLeftState)
        self.backRightModule.applyState(backRightState)
