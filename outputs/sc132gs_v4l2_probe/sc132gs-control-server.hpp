// SPDX-License-Identifier: GPL-2.0-only
#pragma once

#include <memory>
#include <string>

class AutoExposure;

class ControlServer final {
public:
    explicit ControlServer(AutoExposure& exposure,
                           std::string path = "/run/sc132gs-ae.sock");
    ~ControlServer();
    ControlServer(const ControlServer&) = delete;
    ControlServer& operator=(const ControlServer&) = delete;

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};
