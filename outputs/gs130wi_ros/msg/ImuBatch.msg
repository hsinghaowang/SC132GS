# Host monotonic notification/transport times, never individual sample stamps.
string frame_id
uint64 acquisition_id
uint64 host_read_begin_ns
uint64 host_read_end_ns
bool interrupt_time_valid
uint64 host_interrupt_ns
bool host_sample_time_validated
bool frame_association_validated
ImuSample[] samples
