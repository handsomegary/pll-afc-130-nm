// Synthesizable synchronous controller specification for the 100 MHz adaptation.
// The physical MOS builder separately supplies the phase-selected clock front end,
// native Gray counters, matched two-register CDC pipelines and overflow detection.
// No timestamp, real-valued frequency estimate or ideal oscillator is used here.
module afc2009_controller (
    input  wire       ref_clk,
    input  wire       reset,
    input  wire       start,
    input  wire       epoch_seen,
    input  wire       counts_valid,
    input  wire       counter_fault,
    input  wire [7:0] count_lead,
    input  wire [7:0] count_lag,
    input  wire [7:0] count_div,
    output reg  [4:0] code,
    output reg  [2:0] round_index,
    output wire       frontend_reset,
    output wire       frontend_freeze,
    output wire       trial_arm,
    output wire       hold,
    output wire       pfd_reset,
    output reg        fine_enable,
    output reg        done,
    output reg        fail,
    output reg        candidate_provisional,
    output reg        decision_valid,
    output reg  [1:0] decision,
    output reg        update,
    output reg  [3:0] state
);
    localparam IDLE=0, SETTLE=1, ARM=2, MEASURE=3,
               DRAIN=4, APPLY=5, DONE=6, FAILED=7;
    localparam NONE=0, SLOW=1, FAST=2, NEAR=3;
    reg [4:0] step;
    reg [8:0] ticks;
    reg [1:0] previous_direction;
    reg direction_seen_once;
    wire slow = ({1'b0,count_lag} >= {1'b0,count_div}+9'd2);
    wire fast = ({1'b0,count_div} >= {1'b0,count_lead}+9'd2);
    wire [1:0] direction = slow ? SLOW : (fast ? FAST : NONE);
    assign frontend_reset = reset || state==IDLE || state==SETTLE;
    assign frontend_freeze = state==DRAIN || state==APPLY ||
                             state==DONE || state==FAILED;
    assign trial_arm = state==ARM || state==MEASURE;
    assign hold = !fine_enable;
    assign pfd_reset = reset || !fine_enable;
    always @(posedge ref_clk or posedge reset) begin
        if (reset) begin
            state<=IDLE; code<=5'd16; round_index<=0; step<=5'd8;
            ticks<=0; previous_direction<=NONE; direction_seen_once<=0;
            fine_enable<=0; done<=0; fail<=0; candidate_provisional<=0;
            decision_valid<=0; decision<=NONE; update<=0;
        end else begin
            update<=0;
            case(state)
                IDLE: if(start) begin
                    code<=5'd16; round_index<=0; step<=5'd8; ticks<=0;
                    previous_direction<=NONE; direction_seen_once<=0;
                    decision_valid<=0; decision<=NONE;
                    fine_enable<=0; done<=0; fail<=0;
                    candidate_provisional<=0; state<=SETTLE;
                end
                SETTLE: begin
                    if(ticks==3) begin ticks<=0; state<=ARM; end
                    else ticks<=ticks+1'b1;
                end
                ARM: begin
                    if(counter_fault) begin state<=FAILED; fail<=1; end
                    else if(epoch_seen) begin
                        ticks<=0; state<=MEASURE;
                        previous_direction<=NONE; direction_seen_once<=0;
                    end else if(ticks==31) begin state<=FAILED; fail<=1; end
                    else ticks<=ticks+1'b1;
                end
                MEASURE: begin
                    ticks<=ticks+1'b1;
                    if(counter_fault || (counts_valid && slow && fast) ||
                       ticks==191) begin state<=FAILED; fail<=1; end
                    else if(counts_valid) begin
                        if(direction!=NONE) begin
                            if(direction_seen_once &&
                               previous_direction==direction) begin
                                decision<=direction; decision_valid<=1;
                                ticks<=0; state<=DRAIN;
                            end else begin
                                previous_direction<=direction;
                                direction_seen_once<=1;
                            end
                        end else begin
                            previous_direction<=NONE; direction_seen_once<=0;
                            if(count_lag>=8'd128) begin
                                decision<=NEAR; decision_valid<=1;
                                ticks<=0; state<=DRAIN;
                            end
                        end
                    end
                end
                DRAIN: begin
                    if(ticks==1) begin ticks<=0; state<=APPLY; end
                    else ticks<=ticks+1'b1;
                end
                APPLY: begin
                    if((code==1 && decision==FAST) ||
                       (code==31 && decision==SLOW)) begin
                        fail<=1; state<=FAILED;
                    end else if(decision==NEAR || round_index==4) begin
                        // The final code is the code actually measured, never an
                        // untested extra SAR code. Closed-loop capture qualifies it.
                        candidate_provisional<=1; done<=1; ticks<=0; state<=DONE;
                    end else begin
                        if(decision==SLOW) code<=code+step;
                        else code<=code-step;
                        step<=step>>1; round_index<=round_index+1'b1;
                        ticks<=0; decision_valid<=0; update<=1; state<=SETTLE;
                    end
                end
                DONE: begin
                    if(ticks==1) fine_enable<=1;
                    else ticks<=ticks+1'b1;
                end
                FAILED: begin fine_enable<=0; done<=0; fail<=1; end
                default: begin state<=FAILED; fine_enable<=0; fail<=1; end
            endcase
        end
    end
endmodule
